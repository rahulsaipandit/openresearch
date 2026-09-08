"""
PreInterviewDrillSkill — SM-2 spaced-repetition practice over previously
asked questions in a candidate's cognitive memory.

Deliberately a fresh implementation, not a call into store/skills_store.py —
per design discussion, that store serves the existing single-user,
pre-interview JD/resume research feature (schemas/interview.py) and stays
untouched. This skill instead drills questions already recorded by
LiveInterviewCoachSkill (memory/interview_memory.py's questions/*.md),
so a question answered live during a real Pluely session also becomes
practice material later — the two skills share the same memory.

Same SM-2 algorithm as store/skills_store.py (SuperMemo SM-2, Woźniak 1987):
  quality 0-2 = failed recall  → reset repetitions, interval back to 1 day
  quality 3-5 = correct recall → advance interval using EF
"""

from datetime import date, timedelta
from typing import Optional

from agents.interview.skills.base import Skill
from memory.interview_memory import InterviewMemoryStore
from schemas.interview_memory import QuestionRecord


def _sm2(ef: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    new_ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ef = max(1.3, round(new_ef, 4))

    if quality < 3:
        return new_ef, 1, 0

    if reps == 0:
        new_interval = 1
    elif reps == 1:
        new_interval = 6
    else:
        new_interval = max(1, round(interval * new_ef))

    return new_ef, new_interval, reps + 1


class PreInterviewDrillSkill(Skill):
    name = "pre_interview_drill"
    description = "SM-2 spaced-repetition practice scheduling over previously asked questions."

    def apply(self, memory: InterviewMemoryStore, *, action: str, **kwargs) -> object:
        if action == "due_today":
            return self.due_today(memory, as_of_date=kwargs.get("as_of_date"))
        if action == "record_review":
            return self.record_review(
                memory, question_id=kwargs["question_id"], quality=kwargs["quality"]
            )
        raise ValueError(f"Unknown action {action!r}. Use 'due_today' or 'record_review'.")

    def due_today(
        self, memory: InterviewMemoryStore, as_of_date: Optional[str] = None
    ) -> list[dict]:
        today = date.fromisoformat(as_of_date) if as_of_date else date.today()
        due: list[dict] = []
        for record in memory.list_questions():
            review_date = (
                date.fromisoformat(record.next_review_date) if record.next_review_date else today
            )
            if review_date <= today:
                due.append(
                    {
                        "id": record.id,
                        "question": record.question_text,
                        "topic": record.topic,
                        "days_overdue": (today - review_date).days,
                        "repetitions": record.repetitions,
                        "ease_factor": record.ease_factor,
                        "last_quality": record.last_quality,
                    }
                )
        due.sort(key=lambda d: (-d["days_overdue"], d["topic"]))
        return due

    def record_review(
        self, memory: InterviewMemoryStore, question_id: str, quality: int
    ) -> Optional[QuestionRecord]:
        if not 0 <= quality <= 5:
            raise ValueError(f"quality must be 0-5, got {quality}")

        record = memory.get_question(question_id)
        if not record:
            return None

        new_ef, new_interval, new_reps = _sm2(
            record.ease_factor, record.interval_days, record.repetitions, quality
        )
        record.ease_factor = new_ef
        record.interval_days = new_interval
        record.repetitions = new_reps
        record.next_review_date = (date.today() + timedelta(days=new_interval)).isoformat()
        record.last_reviewed = date.today().isoformat()
        record.last_quality = quality

        memory.update_question_drill_state(record)
        return record
