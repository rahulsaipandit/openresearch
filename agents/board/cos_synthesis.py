"""
CoSSynthesis — Node 9 of the Executive Board pipeline.

The Chief of Staff synthesis agent. Reads all BoardMemberView outputs and the
ConflictReport, then produces the final BoardBriefing for the CEO.
"""

import json
import logging
from datetime import date

from agents.api_utils import LLMClient
from schemas.board import (
    BoardMemberView, ConflictReport, BoardBriefing,
    ActionItem, Decision, Conflict
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Chief of Staff writing the CEO's weekly executive briefing.
You have read the views from all board members and the conflict analysis.

Your job:
1. Write a 3-5 sentence executive summary the CEO can read in 60 seconds
2. Assign a 0-10 org health score with clear reasoning
3. Surface the 3-5 red flags requiring immediate CEO attention
4. List the top 5 priorities for the week, ranked
5. Define concrete action items: owner, deadline, what exactly they must do
6. Recommend decisions the CEO needs to make
7. Summarize cross-team conflicts that need CEO arbitration

Be direct. Do not repeat what each VP said — synthesize across them.
Return ONLY valid JSON."""

BRIEFING_SCHEMA = """{
  "session_date": "<YYYY-MM-DD>",
  "mode": "<weekly_review|decision_advisory|health_scan>",
  "executive_summary": "<3-5 sentence CEO-level summary>",
  "org_health_score": <float 0-10>,
  "red_flags": ["<immediate action item>", ...],
  "cross_team_conflicts": [
    {"description": "<string>", "parties": ["<agent_id>", ...],
     "severity": "<low|medium|high>", "suggested_resolution": "<string or null>"}
  ],
  "top_priorities": ["<ranked priority>", ...],
  "action_items": [
    {"description": "<specific action>", "owner": "<role or person>",
     "due_date": "<YYYY-MM-DD or null>", "priority": "<low|medium|high>"}
  ],
  "decisions_recommended": [
    {"title": "<string>", "description": "<string>",
     "owner": "<string or null>", "due_date": "<YYYY-MM-DD or null>",
     "options": ["<option>", ...], "recommended": "<string or null>"}
  ]
}"""


class CoSSynthesisAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def synthesize(
        self,
        board_views: list[BoardMemberView],
        conflict_report: ConflictReport,
        session_mode: str = "weekly_review",
    ) -> BoardBriefing:
        if self.verbose:
            print("  [CoSSynthesis] Writing executive briefing...")

        prompt = self._build_prompt(board_views, conflict_report, session_mode)
        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,
        )

        try:
            data = json.loads(raw)
            data["board_member_views"] = [v.model_dump() for v in board_views]
            return BoardBriefing(**data)
        except Exception as e:
            logger.warning(f"CoSSynthesis JSON parse failed: {e}\nRaw: {raw[:400]}")
            return BoardBriefing(
                session_date=date.today().isoformat(),
                mode=session_mode,
                executive_summary="Synthesis failed — manual review of board member views required.",
                org_health_score=5.0,
                board_member_views=board_views,
            )

    def _build_prompt(
        self,
        board_views: list[BoardMemberView],
        conflict_report: ConflictReport,
        session_mode: str,
    ) -> str:
        lines = [f"Session mode: {session_mode}", f"Date: {date.today().isoformat()}", ""]

        for view in board_views:
            lines.append(f"=== {view.role} ===")
            for f in view.key_findings:
                lines.append(f"  Finding: {f}")
            high_risks = [r for r in view.risks if r.severity in ("high", "critical")]
            for r in high_risks:
                lines.append(f"  Risk [{r.severity}]: {r.description}")
            for rec in view.recommendations[:2]:
                lines.append(f"  Rec: {rec}")
            for q in view.questions_for_ceo[:2]:
                lines.append(f"  CEO Q: {q}")

        lines.append(f"\n=== Conflict Report ===")
        lines.append(conflict_report.summary or "No summary available.")
        for c in conflict_report.conflicts:
            lines.append(f"  Conflict [{c.severity}]: {c.description} (parties: {', '.join(c.parties)})")
        for rc in conflict_report.resource_contentions:
            lines.append(f"  Resource contention: {rc}")

        lines.append(f"\nWrite a BoardBriefing JSON matching this schema:\n{BRIEFING_SCHEMA}")
        return "\n".join(lines)
