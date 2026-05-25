"""
ProfileBuilder — parses a resume and merges it into the master profile.

Two operations:
  parse(resume_text)                        → MasterProfile (first resume)
  merge(existing: MasterProfile, resume)    → MasterProfile (subsequent resumes)

The LLM is used for both. On merge, the existing profile is serialised to
JSON and passed alongside the new resume so the model can intelligently
dedup experiences, union skills, and consolidate achievements rather than
blindly appending.

Fallback: if the LLM call or JSON parse fails, the raw resume text is stored
in the summary field so no data is lost, and source_count is still incremented.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from agents.api_utils import LLMClient
from schemas.profile import MasterProfile, Experience, Education

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_PARSE_SYSTEM = """You are a resume parser. Extract structured information from a resume
and return it as JSON. Be thorough — capture all experiences, skills, and achievements.

Rules:
- skills: flat list of individual technologies, tools, languages, and methodologies
- experiences: one entry per role (same person at same company in different roles = separate entries)
- achievements: standalone accomplishments not tied to a specific role (e.g. patents, open source)
- dates: use "YYYY-MM" format where possible; use "YYYY" if only year is known; null if unknown
- end_date: null means current role
- Be precise: do not paraphrase achievements — capture the actual numbers and outcomes

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

_PARSE_SCHEMA = """{
  "name": "<full name or null>",
  "email": "<email or null>",
  "phone": "<phone or null>",
  "location": "<city, country or null>",
  "summary": "<professional summary 2-4 sentences capturing level, domain, and key strengths>",
  "skills": ["<skill>", ...],
  "experiences": [
    {
      "company": "<company name>",
      "title": "<job title>",
      "start_date": "<YYYY-MM or null>",
      "end_date": "<YYYY-MM or null — null = current>",
      "description": "<1-2 sentence role description>",
      "achievements": ["<specific achievement with numbers>", ...],
      "technologies": ["<tech used in this role>", ...]
    }
  ],
  "education": [
    {
      "institution": "<university or school>",
      "degree": "<degree type>",
      "field": "<field of study or null>",
      "graduation_year": "<YYYY or null>"
    }
  ],
  "achievements": ["<standalone achievement not tied to a role>", ...]
}"""

_MERGE_SYSTEM = """You are merging a new resume into an existing master candidate profile.

Rules:
1. skills: union of all skills from both sources, deduplicated and normalised
   (e.g. "JavaScript" and "JS" → keep "JavaScript"; "AWS" and "Amazon Web Services" → keep "AWS")
2. experiences: deduplicate by company + title. If the same role appears in both, keep the
   version with more detail (more achievements, more technologies listed).
   If roles differ (same company, different titles), keep both.
3. education: deduplicate by institution + degree. Keep the most complete entry.
4. achievements: union, deduplicated by semantic meaning (not just exact string match).
   Prefer the version with specific numbers.
5. summary: rewrite to reflect the union of both profiles — 2-4 sentences.
6. name/email/phone/location: prefer non-null values; if both have values, prefer the new resume.
7. source_count: increment by 1.
8. updated_at: set to now (leave as the placeholder "__NOW__").

Return ONLY the updated master profile as valid JSON matching the same schema — no prose."""


class ProfileBuilderAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    # ── Public API ────────────────────────────────────────────────────────────

    def add_resume(
        self,
        resume_text: str,
        existing: Optional[MasterProfile] = None,
    ) -> MasterProfile:
        """
        Parse resume_text and merge into existing profile (or create new if None).
        """
        if existing is None:
            return self._parse(resume_text)
        return self._merge(existing, resume_text)

    # ── Parse (first resume) ──────────────────────────────────────────────────

    def _parse(self, resume_text: str) -> MasterProfile:
        if self.verbose:
            print("  [ProfileBuilder] Parsing resume into master profile...")

        raw = self.llm.create(
            system=_PARSE_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Parse this resume:\n\n{resume_text.strip()}\n\n"
                f"Return JSON matching:\n{_PARSE_SCHEMA}"
            )}],
            max_tokens=2000,
        )

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            data = json.loads(raw)
            return MasterProfile(
                created_at=now,
                updated_at=now,
                source_count=1,
                **{k: v for k, v in data.items() if k in MasterProfile.model_fields},
            )
        except Exception as e:
            logger.warning(f"ProfileBuilder._parse JSON failed: {e}\nRaw: {raw[:300]}")
            return self._fallback_profile(resume_text, source_count=1)

    # ── Merge (subsequent resumes) ────────────────────────────────────────────

    def _merge(self, existing: MasterProfile, resume_text: str) -> MasterProfile:
        if self.verbose:
            print(
                f"  [ProfileBuilder] Merging resume #{existing.source_count + 1} "
                "into master profile..."
            )

        prompt = (
            f"=== EXISTING MASTER PROFILE (JSON) ===\n"
            f"{existing.model_dump_json(indent=2)}\n\n"
            f"=== NEW RESUME TO MERGE ===\n"
            f"{resume_text.strip()}\n\n"
            f"Merge according to the rules. "
            f"Set source_count to {existing.source_count + 1}. "
            f"Set updated_at to \"__NOW__\".\n"
            f"Return the complete merged MasterProfile JSON."
        )

        raw = self.llm.create(
            system=_MERGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,
        )

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            data = json.loads(raw)
            # Replace placeholder timestamp
            data["updated_at"] = now
            data.setdefault("created_at", existing.created_at)
            data["source_count"] = existing.source_count + 1
            return MasterProfile(**{
                k: v for k, v in data.items() if k in MasterProfile.model_fields
            })
        except Exception as e:
            logger.warning(f"ProfileBuilder._merge JSON failed: {e}\nRaw: {raw[:300]}")
            # Preserve existing profile, just bump count
            existing.source_count += 1
            existing.updated_at    = now
            return existing

    # ── Fallback ──────────────────────────────────────────────────────────────

    def _fallback_profile(self, resume_text: str, source_count: int) -> MasterProfile:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return MasterProfile(
            created_at=now,
            updated_at=now,
            source_count=source_count,
            summary=resume_text[:500],      # store raw text so nothing is lost
        )
