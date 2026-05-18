"""
Base class for all board member agents.

Each board member agent:
1. Receives an OrgSnapshot
2. Calls the LLM with its own persona system prompt
3. Returns a BoardMemberView

Subclasses only need to define:
  - AGENT_ID: str
  - ROLE: str
  - SYSTEM_PROMPT: str
"""

import json
import logging
from abc import ABC

from agents.api_utils import LLMClient
from schemas.board import OrgSnapshot, BoardMemberView, Risk

logger = logging.getLogger(__name__)

VIEW_SCHEMA = """{
  "agent_id": "<string>",
  "role": "<string>",
  "key_findings": ["<finding>", ...],
  "risks": [{"description": "<string>", "severity": "<low|medium|high|critical>", "owner": "<string or null>", "mitigation": "<string or null>"}, ...],
  "recommendations": ["<recommendation>", ...],
  "questions_for_ceo": ["<question>", ...],
  "confidence": <float 0.0-1.0>
}"""


class BoardMemberBase(ABC):
    AGENT_ID: str = ""
    ROLE: str     = ""
    SYSTEM_PROMPT: str = ""

    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def analyze(self, snapshot: OrgSnapshot, session_mode: str = "weekly_review") -> BoardMemberView:
        if self.verbose:
            print(f"  [{self.ROLE}] Analyzing org snapshot...")

        prompt = self._build_prompt(snapshot, session_mode)
        raw = self.llm.create(
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )

        try:
            data = json.loads(raw)
            data["agent_id"] = self.AGENT_ID
            data["role"]     = self.ROLE
            return BoardMemberView(**data)
        except Exception as e:
            logger.warning(f"[{self.ROLE}] JSON parse failed: {e}\nRaw: {raw[:300]}")
            return BoardMemberView(
                agent_id=self.AGENT_ID,
                role=self.ROLE,
                key_findings=["Analysis failed — raw LLM output unparseable"],
                confidence=0.0,
            )

    def _build_prompt(self, snapshot: OrgSnapshot, session_mode: str) -> str:
        import json as _json
        lines = [
            f"Session mode: {session_mode}",
            f"Snapshot date: {snapshot.snapshot_date}",
            "",
            f"Org metrics: headcount={snapshot.org_metrics.total_headcount}, "
            f"open_roles={snapshot.org_metrics.open_roles}, "
            f"projects_at_risk={snapshot.org_metrics.projects_at_risk_count}",
            "",
        ]

        for team in snapshot.teams:
            lines.append(f"Team: {team.team_name} (VP: {team.vp_name}, headcount: {team.headcount})")
            lines.append(f"  Budget: {team.budget_status or 'unknown'}, Morale: {team.morale_signal or 'unknown'}")
            if team.blockers:
                lines.append(f"  Blockers: {'; '.join(team.blockers[:3])}")
            at_risk = [p for p in team.active_projects if p.status in ("at_risk", "blocked")]
            if at_risk:
                lines.append(f"  At-risk projects: {', '.join(p.name for p in at_risk)}")

        if snapshot.active_initiatives:
            lines.append("\nActive initiatives:")
            for init in snapshot.active_initiatives[:5]:
                lines.append(f"  - {init.name} ({init.status}): {init.description[:100]}")

        if snapshot.open_risks:
            lines.append("\nOpen risks:")
            for r in snapshot.open_risks[:5]:
                lines.append(f"  - [{r.severity}] {r.description}")

        if snapshot.decisions_pending:
            lines.append("\nPending decisions:")
            for d in snapshot.decisions_pending[:3]:
                lines.append(f"  - {d.title}: {d.description[:100]}")

        lines.append(f"\nReturn a BoardMemberView JSON matching this schema:\n{VIEW_SCHEMA}")
        return "\n".join(lines)
