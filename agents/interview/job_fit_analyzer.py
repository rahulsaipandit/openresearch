"""
JobFitAnalyzer — Node 1 of the interview research pipeline.

Compares the candidate's profile against the job description and produces
a FitVerdict with an honest score, matched strengths, gaps, and deal-breakers.

Design principle (from Precision Questioning framework):
  - Never soften a deal-breaker.
  - Every gap names the specific skill, years, or domain knowledge that is missing.
  - The 80/20 rule applies: surface the 20% of gaps that cause 80% of rejections.
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.interview import FitVerdict

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a brutally honest technical recruiter and hiring manager with 20 years
of experience across software engineering, product, and executive roles.

Your job is NOT to validate candidates or encourage applications — your job is to give
the candidate the honest signal a hiring manager has but never tells them.

Rules:
1. Apply the Pareto principle: identify the 20% of gaps that would cause 80% of rejections.
2. Name technologies, years of experience, domain knowledge, and level mismatches explicitly.
3. A "deal-breaker" is a hard JD requirement the candidate clearly does not meet.
   If there are none, return an empty list — do not invent them.
4. Score 0–10: 9–10 = near-perfect match; 7–8 = strong, worth pursuing; 5–6 = stretch;
   below 5 = not recommended without significant upskilling.
5. The summary must name the single strongest match and the single biggest risk in plain language.
6. Never use words like "strong candidate", "great fit", or "exciting opportunity" —
   those are recruiter filler. Be a hiring manager writing notes to themselves.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

FIT_SCHEMA = """{
  "overall_score": <float 0.0–10.0>,
  "match_strengths": [
    "<specific experience or skill from profile that directly satisfies a JD requirement>",
    ...
  ],
  "gaps": [
    "<specific missing skill, years, or qualification — e.g. 'No distributed systems experience; JD requires 3+ years'>",
    ...
  ],
  "deal_breakers": [
    "<hard JD requirement the candidate clearly does not meet — leave empty list if none>",
    ...
  ],
  "recommendation": "<strong_fit | worth_pursuing | stretch | not_recommended>",
  "summary": "<2–3 sentences: honest assessment naming the biggest strength and biggest risk>"
}"""


class JobFitAnalyzerAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def analyze(
        self,
        jd_text: str,
        profile_text: str,
        company_name: str,
        role_title: str,
    ) -> FitVerdict:
        prompt = self._build_prompt(jd_text, profile_text, company_name, role_title)

        if self.verbose:
            print(f"  [JobFitAnalyzer] Analyzing fit for {role_title} at {company_name}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )

        try:
            data = json.loads(raw)
            return FitVerdict(**data)
        except Exception as e:
            logger.warning(f"JobFitAnalyzer JSON parse failed: {e}\nRaw: {raw[:300]}")
            return self._fallback_verdict()

    def _build_prompt(
        self,
        jd_text: str,
        profile_text: str,
        company_name: str,
        role_title: str,
    ) -> str:
        return f"""Role: {role_title}
Company: {company_name}

=== JOB DESCRIPTION ===
{jd_text.strip()}

=== CANDIDATE PROFILE ===
{profile_text.strip()}

Produce a FitVerdict JSON matching this schema:
{FIT_SCHEMA}"""

    def _fallback_verdict(self) -> FitVerdict:
        return FitVerdict(
            overall_score=0.0,
            match_strengths=[],
            gaps=["Analysis failed — could not parse LLM response."],
            deal_breakers=[],
            recommendation="not_recommended",
            summary="Fit analysis could not be completed. Please retry.",
        )
