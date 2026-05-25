"""
QuestionGenerator — Node 3 of the interview research pipeline.

Generates a company-specific, gap-weighted set of interview questions.

Weighting logic:
  - Behavioural questions target identified gaps from FitVerdict first,
    then confirmed strengths (to build confidence and catch depth-of-answer issues).
  - Technical questions are derived from the JD's explicit requirements.
  - Culture-fit questions map to the company's stated values from CompanyProfile.
  - Curveball questions reflect the company's known interview style edge cases.
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.interview import FitVerdict, CompanyProfile, QuestionSet

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior interviewer who writes questions for technical and leadership
interviews. Your questions are specific, non-generic, and designed to reveal the truth about
a candidate — not to help them perform well, but to surface signal.

Rules:
1. Behavioural questions must target the candidate's identified GAPS first. If a candidate
   has no distributed systems experience but the JD requires it, ask about their closest
   analogue — it will expose the gap clearly.
2. Technical questions must match the explicit technical requirements in the JD exactly.
   Do not ask about technologies not mentioned in the JD.
3. Culture-fit questions must use the company's own language / principles where applicable.
4. Curveball questions should reflect what this specific company is known for asking —
   not generic puzzles.
5. Every question must be specific enough that a vague answer is obviously insufficient.
   Avoid: "Tell me about a time you led a project."
   Prefer: "Tell me about the last time a project you led missed a milestone. What was
            your ownership of the miss and what did you change afterward?"

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

QUESTION_SCHEMA = """{
  "behavioural": [
    "<specific behavioural question — targets identified gaps or probes depth on strengths>",
    ...
  ],
  "technical": [
    "<specific technical question derived from an explicit JD requirement>",
    ...
  ],
  "culture_fit": [
    "<question that tests a specific value or principle the company is known to assess>",
    ...
  ],
  "curveball": [
    "<question that reflects this company's known edge-case interview style>",
    ...
  ]
}"""

# Target question counts per category
_QUESTION_COUNTS = {
    "behavioural": 5,
    "technical":   5,
    "culture_fit": 3,
    "curveball":   2,
}


class QuestionGeneratorAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def generate(
        self,
        jd_text: str,
        fit: FitVerdict,
        company: CompanyProfile,
        company_name: str,
        role_title: str,
    ) -> QuestionSet:
        prompt = self._build_prompt(jd_text, fit, company, company_name, role_title)

        if self.verbose:
            print(f"  [QuestionGenerator] Generating questions for {role_title} at {company_name}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )

        try:
            data = json.loads(raw)
            return QuestionSet(**data)
        except Exception as e:
            logger.warning(f"QuestionGenerator JSON parse failed: {e}\nRaw: {raw[:300]}")
            return self._fallback_questions(role_title)

    def _build_prompt(
        self,
        jd_text: str,
        fit: FitVerdict,
        company: CompanyProfile,
        company_name: str,
        role_title: str,
    ) -> str:
        gaps_block = (
            "\n".join(f"  - {g}" for g in fit.gaps)
            if fit.gaps else "  None identified."
        )
        deal_breaker_block = (
            "\n".join(f"  - {d}" for d in fit.deal_breakers)
            if fit.deal_breakers else "  None."
        )
        strengths_block = (
            "\n".join(f"  - {s}" for s in fit.match_strengths)
            if fit.match_strengths else "  None identified."
        )
        values_block = (
            "\n".join(f"  - {v}" for v in company.known_values)
            if company.known_values else "  Not specified."
        )

        return f"""Role: {role_title}
Company: {company_name}
Interview style: {company.interview_style}

=== JOB DESCRIPTION (excerpt) ===
{jd_text.strip()[:3000]}

=== CANDIDATE FIT ANALYSIS ===
Overall score: {fit.overall_score}/10
Recommendation: {fit.recommendation}

Gaps (prioritise these in behavioural questions):
{gaps_block}

Deal-breakers:
{deal_breaker_block}

Match strengths (probe depth here — don't let them coast):
{strengths_block}

=== COMPANY VALUES TO ASSESS ===
{values_block}

Generate {_QUESTION_COUNTS['behavioural']} behavioural, {_QUESTION_COUNTS['technical']} technical,
{_QUESTION_COUNTS['culture_fit']} culture-fit, and {_QUESTION_COUNTS['curveball']} curveball questions.

Behavioural questions must target the candidate's GAPS first.

Produce a QuestionSet JSON matching this schema:
{QUESTION_SCHEMA}"""

    def _fallback_questions(self, role_title: str) -> QuestionSet:
        return QuestionSet(
            behavioural=[
                f"Tell me about the most complex project you led as a {role_title}.",
                "Describe a time you disagreed with your manager and how you handled it.",
                "Tell me about a time you failed to deliver on a commitment.",
                "How have you handled a situation where a key team member was underperforming?",
                "Describe the last time you had to change your approach based on feedback.",
            ],
            technical=[
                "Walk me through a system you designed end-to-end and the trade-offs you made.",
            ],
            culture_fit=[
                "What does ownership mean to you, and give a recent example.",
                "How do you handle working in ambiguous or fast-changing environments?",
                "Describe how you've raised the bar for your team.",
            ],
            curveball=[
                "What is the most important thing you would change about your current role, and why haven't you?",
                "If you were interviewing me for this role, what would you want to know?",
            ],
        )
