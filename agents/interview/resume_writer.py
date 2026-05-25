"""
ResumeWriterAgent — Node 5 of the interview research pipeline.

Takes the candidate's master profile, the target JD, and the FitVerdict
and produces a TailoredResume: a full resume rewritten to maximise relevance
for this specific role, plus a cover letter opener.

Design principles:
  - Never invent experience. Every bullet must trace back to the master profile.
  - Emphasis is reframing, not fabrication: take real achievements and surface
    the aspects most relevant to the JD.
  - The FitVerdict drives what to lead with (strengths) and what to de-emphasise
    (gaps/deal-breakers get honest, brief treatment — not hidden).
  - tailoring_notes provides a transparency log of every deliberate change so
    the candidate can review what was adjusted and why.

Uses PromptBudget to handle large profiles without context overflow.
"""

import json
import logging

from agents.api_utils import LLMClient, PromptBudget
from schemas.interview import FitVerdict, CompanyProfile, TailoredResume

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a world-class technical recruiter and resume writer who has helped
thousands of engineers land roles at top companies. You understand what hiring managers and ATS
systems look for at different companies and seniority levels.

Your task: take a candidate's master profile and rewrite it as a targeted resume for a specific
role. Rules you must follow:

1. NEVER invent experience the candidate does not have. Every bullet must be traceable to the
   master profile. You may reframe, reorder, and emphasise — not fabricate.

2. Lead with strengths that directly match the JD. Use the FitVerdict's match_strengths to
   identify what to surface first.

3. Reorder experience bullets within each role to lead with the most JD-relevant achievements.
   Drop low-signal bullets (e.g. "maintained documentation") to make room for high-signal ones.

4. Skill section: filter to skills mentioned in the JD or strongly implied by it. Lead with
   the most relevant. Remove skills that are obviously irrelevant to this role.

5. Summary: 3–4 sentences. Open with years of experience + domain. State the highest-relevance
   strength. Name one specific achievement with a number. End with what you bring to this company.

6. Cover letter opener: 2–3 sentences. Specific to this company. Name something real about them
   (product, mission, recent news if known). Connect it to a concrete achievement from the profile.

7. tailoring_notes: list exactly what you changed and why — this is the transparency log.
   e.g. "Moved distributed-systems bullet to first position — JD requires platform-scale experience."

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

RESUME_SCHEMA = """{
  "target_role": "<role title>",
  "target_company": "<company name>",
  "summary": "<3–4 sentence professional summary targeting this role>",
  "highlighted_skills": [
    "<skill 1 — most JD-relevant first>",
    "<skill 2>",
    ...
  ],
  "experience_bullets": [
    "<strongest, most JD-relevant achievement bullet — must include a number>",
    "<second achievement bullet>",
    ...
  ],
  "cover_letter_opener": "<2–3 sentences specific to this company and role>",
  "full_resume_md": "<complete tailored resume in clean Markdown, ready to copy-paste>",
  "tailoring_notes": [
    "<what was changed and why>",
    ...
  ]
}"""

# Fallback when parsing fails — preserves the profile as-is
def _fallback_resume(company_name: str, role_title: str) -> TailoredResume:
    return TailoredResume(
        target_role=role_title,
        target_company=company_name,
        summary="Resume tailoring failed. Use the master profile directly.",
        highlighted_skills=[],
        experience_bullets=[],
        cover_letter_opener="",
        full_resume_md="*Resume tailoring failed — submit master profile directly.*",
        tailoring_notes=["LLM parse error. No changes applied."],
    )


class ResumeWriterAgent:
    """
    Rewrites the candidate's master profile as a targeted resume for a specific JD.

    Args:
        llm:     LLMClient instance
        verbose: print progress to stdout
    """

    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def write(
        self,
        profile_text: str,
        jd_text: str,
        fit: FitVerdict,
        company: CompanyProfile,
        company_name: str,
        role_title: str,
    ) -> TailoredResume:
        """
        Generate a tailored resume from the master profile + JD + FitVerdict.

        Returns TailoredResume. On LLM parse failure, returns a minimal fallback
        rather than raising — the pipeline always completes.
        """
        if self.verbose:
            print(f"  [ResumeWriter] Writing tailored resume for {role_title} at {company_name}...")

        # Build base prompt (without profile, which will be budget-fitted)
        base_prompt = self._build_base_prompt(jd_text, fit, company, company_name, role_title)

        # Use PromptBudget to ensure profile text doesn't overflow the context window
        budget = PromptBudget(model=self.llm.model, reserved_output=4000)
        budget.reserve("system", SYSTEM_PROMPT)
        budget.reserve("instructions", base_prompt)

        fitted = budget.fit([
            ("profile", profile_text.strip(), True),  # required — never drop
        ])

        final_prompt = base_prompt + f"\n\n=== CANDIDATE MASTER PROFILE ===\n{fitted['profile']}"

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": final_prompt}],
            max_tokens=4000,
        )

        try:
            data = json.loads(raw)
            return TailoredResume(**data)
        except Exception as e:
            logger.warning(f"ResumeWriter JSON parse failed: {e}\nRaw: {raw[:300]}")
            return _fallback_resume(company_name, role_title)

    def _build_base_prompt(
        self,
        jd_text: str,
        fit: FitVerdict,
        company: CompanyProfile,
        company_name: str,
        role_title: str,
    ) -> str:
        strengths_block = (
            "\n".join(f"  - {s}" for s in fit.match_strengths)
            if fit.match_strengths else "  None identified."
        )
        gaps_block = (
            "\n".join(f"  - {g}" for g in fit.gaps)
            if fit.gaps else "  None identified."
        )
        deal_breakers_block = (
            "\n".join(f"  - {d}" for d in fit.deal_breakers)
            if fit.deal_breakers else "  None."
        )
        values_block = (
            "\n".join(f"  - {v}" for v in company.known_values)
            if company.known_values else "  Not specified."
        )

        return f"""Target Role: {role_title}
Target Company: {company_name}
Fit Score: {fit.overall_score}/10 ({fit.recommendation})

=== JOB DESCRIPTION ===
{jd_text.strip()}

=== FIT ANALYSIS ===
Confirmed strengths to lead with:
{strengths_block}

Gaps to treat honestly (don't hide, but don't lead with):
{gaps_block}

Deal-breakers (if any — must be addressed directly or omitted with a note):
{deal_breakers_block}

Company values to reference in summary and cover letter:
{values_block}

=== OUTPUT SCHEMA ===
{RESUME_SCHEMA}

Instructions:
1. The full_resume_md must be a complete, submission-ready resume in clean Markdown.
   Include: Summary, Skills, Experience (reverse chronological), Education.
2. Within each Experience entry, reorder bullets to lead with the most JD-relevant achievement.
3. highlighted_skills is the extracted skills list used in the Skills section — ordered by JD relevance.
4. experience_bullets is a flat list of your top 5–7 achievement bullets across all roles.
5. Every achievement bullet must include a specific number or outcome (no vague claims).
6. tailoring_notes must list every deliberate change made vs. the original profile."""
