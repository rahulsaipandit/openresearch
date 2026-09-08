"""
LiveInterviewCoachSkill — the retrieval + answer-generation flow behind
POST /v1/interview/answer (requirements doc §2).

Two-phase, to respect the ~2s first-token latency budget and the §6 open
item that judge scoring must not block the *next* question's answer:
  1. apply()            — retrieval (vector + graph) + answer generation.
                           Returns immediately; server streams the text back.
  2. judge_and_record()  — runs AFTER the answer has been sent, as a
                           background task. Scores the answer, rewrites the
                           question record with its real topic, and appends
                           an Assessment (which recomputes the topic summary).
"""

import logging
from typing import Optional

from agents.api_utils import LLMClient
from agents.interview.memory_judge_agent import MemoryJudgeAgent
from agents.interview.skills.base import Skill
from memory.interview_memory import InterviewMemoryStore
from schemas.interview_memory import (
    AnswerResult,
    AnswerStyle,
    Assessment,
    MatchedSource,
    QuestionRecord,
    TopicSummary,
)

logger = logging.getLogger(__name__)

_FORMAT_INSTRUCTIONS = {
    "full_text": "Answer in full, read-aloud-ready sentences.",
    "list": "Answer as short bulleted key points, one per line — no paragraphs.",
    "keywords": (
        "Answer as minimal standalone words or short phrases, one per line, "
        "separated by newlines. Do NOT write a paragraph — each line becomes "
        "its own chip in the UI, so a paragraph will render as one broken chip."
    ),
}
_DEPTH_INSTRUCTIONS = {
    "one_liner": "Keep it to a single sentence or line.",
    "balanced": "A few sentences — enough to be complete, not exhaustive.",
    "detailed": "Thorough — cover context, specifics, and a concrete outcome/number.",
}


class LiveInterviewCoachSkill(Skill):
    name = "live_interview_coach"
    description = "Real-time retrieval-grounded answer generation for a live interview question."

    def __init__(self, llm: LLMClient, judge: MemoryJudgeAgent):
        self.llm = llm
        self.judge = judge

    def apply(
        self,
        memory: InterviewMemoryStore,
        *,
        question: str,
        session_id: str,
        conversation_history: Optional[list[dict]] = None,
        answer_style: Optional[AnswerStyle] = None,
    ) -> AnswerResult:
        answer_style = answer_style or AnswerStyle()
        conversation_history = conversation_history or []
        profile = memory.get_profile()
        context = memory.retrieve_context(question)

        system_prompt = self._build_system_prompt(profile, answer_style)
        user_prompt = self._build_user_prompt(context, conversation_history, question)

        answer_text = self.llm.create(
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=700,
        )

        matched_sources = [
            MatchedSource(id=e.id, title=e.title, category=e.category)
            for e in context.matched_answer_bank
        ]
        provisional_topic = context.topic_summary.topic if context.topic_summary else "uncategorized"

        record = memory.record_question(
            QuestionRecord(
                id="",
                candidate_id=memory.candidate_id,
                session_id=session_id,
                question_text=question,
                topic=provisional_topic,
                answer_text=answer_text,
                matched_sources=matched_sources,
            )
        )

        return AnswerResult(
            answer_text=answer_text,
            matched_sources=matched_sources,
            topic=record.topic,
            question_record_id=record.id,
        )

    def judge_and_record(
        self, memory: InterviewMemoryStore, question_record_id: str
    ) -> Optional[TopicSummary]:
        """Run after the answer has already streamed back — see module docstring."""
        record = memory.get_question(question_record_id)
        if not record:
            logger.warning(f"judge_and_record: question {question_record_id!r} not found")
            return None

        known_topics = [t.topic for t in memory.list_topic_summaries()]
        verdict = self.judge.judge(record.question_text, record.answer_text, known_topics)
        record.topic = verdict["topic"]
        record.judge_score = verdict["judge_score"]
        record.judge_rationale = verdict["rationale"]
        memory.update_question_after_judge(record)

        summary = memory.record_assessment(
            Assessment(
                id="",
                candidate_id=memory.candidate_id,
                topic=record.topic,
                question_ref=f"questions/{record.id}.md",
                judge_score=verdict["judge_score"],
                source="llm_judge",
                rationale=verdict["rationale"],
            )
        )
        memory.record_topic_co_occurrence([record.topic, *summary.related_topics])
        return summary

    # ── Prompt construction ──────────────────────────────────────────────────

    def _build_system_prompt(self, profile, answer_style: AnswerStyle) -> str:
        return f"""You are an interview coaching assistant, generating a real-time \
answer for a candidate currently mid-interview. Ground your answer in the \
candidate's own resume, job target, and prior answers when relevant — never \
invent specifics (numbers, company names, outcomes) that weren't given to you.

Candidate resume:
{profile.resume_text or "(not provided)"}

Target job description:
{profile.job_description_text or "(not provided)"}

Custom instructions from the candidate:
{profile.custom_instructions or "(none)"}

Format: {_FORMAT_INSTRUCTIONS[answer_style.format]}
Depth: {_DEPTH_INSTRUCTIONS[answer_style.depth]}
"""

    def _build_user_prompt(self, context, conversation_history: list[dict], question: str) -> str:
        sections = []
        if context.matched_answer_bank:
            bank_text = "\n\n".join(
                f"[{e.category}] {e.title}:\n{e.content}" for e in context.matched_answer_bank
            )
            sections.append(f"## Candidate's own relevant answer-bank material\n{bank_text}")
        if context.topic_summary and context.topic_summary.notes:
            sections.append(
                f"## Coaching notes on this topic ({context.topic_summary.topic}, "
                f"mastery {context.topic_summary.mastery_score:.2f})\n{context.topic_summary.notes}"
            )
        if conversation_history:
            history_text = "\n".join(
                f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in conversation_history[-6:]
            )
            sections.append(f"## Recent conversation\n{history_text}")

        sections.append(f"## Question to answer now\n{question}")
        return "\n\n".join(sections)
