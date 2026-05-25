"""
SkillsStore — persistent SM-2 spaced-repetition tracker for interview questions.

Algorithm: SuperMemo SM-2 (Piotr Woźniak, 1987)
  quality 0–2 = failed recall  → reset repetitions, interval stays at 1 day
  quality 3–5 = correct recall → advance interval using EF
  EF' = EF + (0.1 − (5−q) × (0.08 + (5−q) × 0.02))
  EF' = max(1.3, EF')
  interval: 1 → 6 → round(prev × EF) for reps 0, 1, 2+

Usage:
    store = SkillsStore()
    store.add_questions(questions, company, role)   # after a pipeline run
    due   = store.due_today()                       # returns DueQuestion list
    store.record_review(question_id, quality=4)     # after a mock session
    store.annotate(question_id, "need to quantify the result more")
"""

import hashlib
import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from schemas.skills import TrackedQuestion, DueQuestion, SkillsBank, ReviewResult
from schemas.interview import QuestionSet

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "skills.json"
_lock = threading.Lock()


def _question_id(question: str) -> str:
    """Stable 12-char ID derived from question text."""
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:12]


def _sm2(ef: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    """
    Apply one SM-2 review step.

    Returns (new_ef, new_interval, new_reps).
    """
    # Update EF regardless of pass/fail (SM-2 spec)
    new_ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ef = max(1.3, round(new_ef, 4))

    if quality < 3:
        # Failed — reset streak, review again tomorrow
        return new_ef, 1, 0

    # Passed — advance interval
    if reps == 0:
        new_interval = 1
    elif reps == 1:
        new_interval = 6
    else:
        new_interval = max(1, round(interval * new_ef))

    return new_ef, new_interval, reps + 1


class SkillsStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────────────────

    def _load(self) -> SkillsBank:
        if not self.path.exists():
            return SkillsBank()
        try:
            with open(self.path, encoding="utf-8") as f:
                return SkillsBank(**json.load(f))
        except Exception as e:
            logger.error(f"SkillsStore._load failed: {e}")
            return SkillsBank()

    def due_today(self, as_of_date: Optional[str] = None) -> list[DueQuestion]:
        """Return all questions due for review today (or as_of_date)."""
        today = as_of_date or date.today().isoformat()
        return self._load().due_today(today)

    def all_questions(self) -> list[TrackedQuestion]:
        return self._load().questions

    def get(self, question_id: str) -> Optional[TrackedQuestion]:
        for q in self._load().questions:
            if q.id == question_id:
                return q
        return None

    def stats(self) -> dict:
        """Summary counts: total, due, by category, average EF."""
        bank = self._load()
        today = date.today().isoformat()
        due   = bank.due_today(today)
        cats  = {}
        for q in bank.questions:
            cats[q.category] = cats.get(q.category, 0) + 1
        avg_ef = (
            round(sum(q.ease_factor for q in bank.questions) / len(bank.questions), 2)
            if bank.questions else 0.0
        )
        return {
            "total":         len(bank.questions),
            "due_today":     len(due),
            "by_category":   cats,
            "average_ef":    avg_ef,
        }

    # ── Write ─────────────────────────────────────────────────────────────────

    def _save(self, bank: SkillsBank) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(bank.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"SkillsStore._save failed: {e}")
            raise

    def add_questions(
        self,
        questions: QuestionSet,
        company_name: str,
        role_title: str,
    ) -> int:
        """
        Add new questions from a pipeline run to the skills bank.
        Questions already in the bank (same ID) are skipped — their SM-2
        state is preserved.

        Returns the count of newly added questions.
        """
        with _lock:
            bank    = self._load()
            existing_ids = {q.id for q in bank.questions}
            added   = 0
            today   = date.today().isoformat()

            category_map = {
                "behavioural":  questions.behavioural,
                "technical":    questions.technical,
                "culture_fit":  questions.culture_fit,
                "curveball":    questions.curveball,
            }

            for category, qs in category_map.items():
                for text in qs:
                    qid = _question_id(text)
                    if qid in existing_ids:
                        continue
                    bank.questions.append(TrackedQuestion(
                        id=qid,
                        question=text,
                        category=category,
                        company_name=company_name,
                        role_title=role_title,
                        next_review_date=today,     # due immediately
                    ))
                    added += 1

            if added:
                self._save(bank)

            return added

    def record_review(
        self,
        question_id: str,
        quality: int,
        notes: Optional[str] = None,
    ) -> Optional[TrackedQuestion]:
        """
        Apply one SM-2 review step for a question.

        quality: 0–5
          0 = complete blackout
          1 = wrong but recalled on seeing answer
          2 = wrong but answer felt familiar
          3 = correct with significant effort
          4 = correct with some hesitation
          5 = perfect recall, no hesitation
        """
        if quality < 0 or quality > 5:
            raise ValueError(f"quality must be 0–5, got {quality}")

        with _lock:
            bank  = self._load()
            today = date.today().isoformat()

            for q in bank.questions:
                if q.id != question_id:
                    continue

                new_ef, new_interval, new_reps = _sm2(
                    q.ease_factor, q.interval, q.repetitions, quality
                )
                next_date = (
                    date.today() + timedelta(days=new_interval)
                ).isoformat()

                q.ease_factor      = new_ef
                q.interval         = new_interval
                q.repetitions      = new_reps
                q.next_review_date = next_date
                q.last_reviewed    = today
                q.last_quality     = quality
                if notes is not None:
                    q.notes = notes

                self._save(bank)
                return q

            logger.warning(f"SkillsStore.record_review: question {question_id!r} not found")
            return None

    def annotate(self, question_id: str, notes: str) -> Optional[TrackedQuestion]:
        """Attach a freetext note to a question without affecting SM-2 state."""
        with _lock:
            bank = self._load()
            for q in bank.questions:
                if q.id == question_id:
                    q.notes = notes
                    self._save(bank)
                    return q
            return None

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "SkillsStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("interview_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "skills.json")
