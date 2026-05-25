"""
AnswerGenerator — Node 4 of the interview research pipeline.

Generates STAR-format answers from the candidate's profile, tailored
to the target company's values and interview style.

Generates answers for behavioural + culture-fit questions only.
Technical questions require demonstrated knowledge, not STAR stories.

Precision Questioning alignment:
  Each STAR answer enforces the same discipline as the CoS agent:
  - result must contain a specific number, date, or measurable outcome
  - tailoring_note explains exactly why the framing lands for this company
  - No vague intensifiers: "significantly improved" → "reduced P95 latency from 900ms to 120ms"
"""

import json
import logging

from agents.api_utils import LLMClient, PromptBudget
from schemas.interview import FitVerdict, CompanyProfile, QuestionSet, STARAnswer, AnswerSet

logger = logging.getLogger(__name__)

# Answer only these categories — technical questions are knowledge, not stories
_ANSWER_CATEGORIES = ("behavioural", "culture_fit")

# Max questions to answer per category (keeps response within token budget)
_MAX_PER_CATEGORY = 4

SYSTEM_PROMPT = """You are an expert interview coach. Your job is to take a candidate's real
professional experience and craft STAR-format answers that are:

1. Grounded in the candidate's actual profile — never invent experience they don't have.
2. Specific: every Result must contain a concrete number, date, or measurable outcome.
   "Improved performance" is not a result. "Reduced deploy time from 45 minutes to 8 minutes" is.
3. Concise: Situation + Task ≤ 3 sentences each. Action and Result can be longer.
4. Tailored: the tailoring_note explains why this specific answer resonates with this company's
   values — reference the company's principles or culture where possible.

If the candidate's profile does not contain enough detail to answer a question with a real
result, still generate the answer but flag it in tailoring_note: "WEAK: candidate should
strengthen this story with specific metrics before using it."

Do not soften or embellish. If the candidate's best result for a question is modest,
say so — a modest real result is better than an impressive invented one.

Return ONLY valid JSON — an array of STARAnswer objects. No prose, no markdown fences."""

ANSWER_SCHEMA = """[
  {
    "question": "<the interview question being answered>",
    "situation": "<1–3 sentences: context, company, team size, stakes>",
    "task": "<1–2 sentences: what you were specifically responsible for>",
    "action": "<3–5 sentences: what YOU did — use 'I', not 'we'>",
    "result": "<1–3 sentences: specific, measurable outcome with numbers and timeframe>",
    "tailoring_note": "<1–2 sentences: why this answer lands for this company's values>"
  },
  ...
]"""


class AnswerGeneratorAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def generate(
        self,
        profile_text: str,
        questions: QuestionSet,
        company: CompanyProfile,
        fit: FitVerdict,
        company_name: str,
    ) -> AnswerSet:
        target_questions = self._select_questions(questions)

        if not target_questions:
            return AnswerSet(answers=[])

        prompt = self._build_prompt(
            profile_text, target_questions, company, fit, company_name
        )

        if self.verbose:
            print(f"  [AnswerGenerator] Generating {len(target_questions)} STAR answers "
                  f"for {company_name}...")

        # Use PromptBudget to ensure profile text doesn't overflow the context window
        budget = PromptBudget(model=self.llm.model, reserved_output=3000)
        budget.reserve("system", SYSTEM_PROMPT)
        budget.reserve("instructions", prompt.split("=== CANDIDATE PROFILE ===")[0])

        fitted = budget.fit([
            ("profile", profile_text.strip(), True),
        ])

        # Rebuild prompt with potentially truncated profile
        final_prompt = self._build_prompt(
            fitted["profile"], target_questions, company, fit, company_name
        )

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": final_prompt}],
            max_tokens=3000,
        )

        try:
            data = json.loads(raw)
            answers = [STARAnswer(**item) for item in data]
            return AnswerSet(answers=answers)
        except Exception as e:
            logger.warning(f"AnswerGenerator JSON parse failed: {e}\nRaw: {raw[:300]}")
            return AnswerSet(answers=[])

    def _select_questions(self, questions: QuestionSet) -> list[str]:
        """Pick the most important questions to generate STAR answers for."""
        selected: list[str] = []

        # Behavioural first — these expose gaps most directly
        selected.extend(questions.behavioural[:_MAX_PER_CATEGORY])

        # Then culture-fit
        selected.extend(questions.culture_fit[:_MAX_PER_CATEGORY])

        return selected

    def _build_prompt(
        self,
        profile_text: str,
        questions: list[str],
        company: CompanyProfile,
        fit: FitVerdict,
        company_name: str,
    ) -> str:
        questions_block = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

        values_block = (
            "\n".join(f"  - {v}" for v in company.known_values)
            if company.known_values else "  Not specified."
        )

        strengths_block = (
            "\n".join(f"  - {s}" for s in fit.match_strengths)
            if fit.match_strengths else "  Not identified."
        )

        return f"""Company: {company_name}
Interview style: {company.interview_style}

Company values to reference in tailoring_notes:
{values_block}

Candidate's confirmed strengths (use these as source material):
{strengths_block}

=== CANDIDATE PROFILE ===
{profile_text}

=== QUESTIONS TO ANSWER ===
{questions_block}

Generate one STARAnswer per question. Return a JSON array matching:
{ANSWER_SCHEMA}

Requirements:
- Results must include specific numbers or dates — never vague outcomes.
- Draw only from the candidate's profile above — do not invent experience.
- tailoring_note must reference {company_name}'s values or interview style specifically."""
