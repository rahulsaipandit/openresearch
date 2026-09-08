"""
MemoryJudgeAgent — scores a candidate's answer against a question for the
interview cognitive memory (docs/openresearch-integration-requirements.md §6).

Hybrid assessment model: this agent produces the automatic llm_judge
Assessment; a candidate_override Assessment (recorded directly by the API
layer, no agent call) can supersede it — see InterviewMemoryStore._recompute_topic_summary().

Runs after the answer has already been generated/streamed to the candidate —
judge latency must not sit on the answer's first-token budget (§2, §6 open
items).
"""

import json
import logging
import re

from agents.api_utils import LLMClient

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """\
You are grading a candidate's interview answer for a personal coaching memory.
You are not the interviewer — you are scoring after the fact so the candidate's
practice history can track their real strengths and weaknesses over time.

Given a question and the candidate's answer, return:
- topic: a short, normalized topic label (lowercase, hyphenated, e.g.
  "system-design", "conflict-resolution", "behavioral-leadership") —
  reuse a close existing label rather than inventing a near-duplicate.
- judge_score: 0.0-1.0, how well the answer addressed the question
  (completeness, specificity, relevance) — not eloquence alone.
- rationale: 1-2 sentences, specific and actionable, referencing what was
  actually said.

Respond with valid JSON only. No extra text.
"""


class MemoryJudgeAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def judge(self, question: str, answer: str, known_topics: list[str]) -> dict:
        """Returns {"topic": str, "judge_score": float, "rationale": str}."""
        topic_hint = (
            f"Existing topics for this candidate (prefer reusing one of these "
            f"if it fits): {', '.join(known_topics)}\n\n"
            if known_topics
            else ""
        )
        prompt = f"""{topic_hint}## Question
{question}

## Candidate's answer
{answer}

Respond with valid JSON:
{{
  "topic": "...",
  "judge_score": 0.0,
  "rationale": "..."
}}
"""
        raw = self.llm.create(
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        try:
            clean = re.sub(r"```(?:json)?|```", "", raw).strip()
            parsed = json.loads(clean)
            return {
                "topic": str(parsed.get("topic", "uncategorized")).strip().lower() or "uncategorized",
                "judge_score": max(0.0, min(1.0, float(parsed.get("judge_score", 0.5)))),
                "rationale": str(parsed.get("rationale", "")),
            }
        except Exception as e:
            logger.warning(f"MemoryJudgeAgent: could not parse judge output ({e}) — using defaults")
            return {"topic": "uncategorized", "judge_score": 0.5, "rationale": ""}
