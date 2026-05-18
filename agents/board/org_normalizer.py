"""
OrgNormalizer — Node 1 of the Executive Board pipeline.

Takes raw data from Jira / Linear / Notion / Slack / documents / manual paste
and normalizes it into a structured OrgSnapshot that all board agents consume.

Uses an LLM pass to handle unstructured text input (manual paste / documents).
Structured API data (Jira/Linear/Notion) is mapped directly.
"""

import json
import logging
from datetime import date
from typing import Optional

from agents.api_utils import LLMClient
from schemas.board import (
    OrgSnapshot, TeamStatus, OrgMetrics, Initiative, Risk, Decision, Project
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an organizational data analyst. Given raw organizational data
(from project management tools, meeting notes, status updates, or documents), extract
and structure it into a normalized org snapshot.

Map teams to their VP owners. Identify projects, blockers, risks, and pending decisions.
Use the provided schema exactly. Return ONLY valid JSON."""

SNAPSHOT_SCHEMA = """{
  "snapshot_date": "<YYYY-MM-DD>",
  "teams": [
    {
      "vp_name": "<string>",
      "team_name": "<string>",
      "headcount": <int>,
      "active_projects": [
        {"name": "<string>", "status": "<on_track|at_risk|blocked|completed>",
         "owner": "<string or null>", "due_date": "<YYYY-MM-DD or null>",
         "blockers": ["<string>", ...], "progress_pct": <int or null>}
      ],
      "blockers": ["<string>", ...],
      "morale_signal": "<green|yellow|red or null>",
      "budget_status": "<on_track|at_risk|over or null>",
      "notes": "<string or null>"
    }
  ],
  "org_metrics": {
    "total_headcount": <int>,
    "open_roles": <int>,
    "sprint_velocity_trend": "<improving|stable|declining or null>",
    "budget_utilization_pct": <float or null>,
    "projects_at_risk_count": <int>
  },
  "active_initiatives": [
    {"name": "<string>", "description": "<string>",
     "status": "<planning|active|blocked|complete>",
     "teams_involved": ["<string>", ...], "target_date": "<YYYY-MM-DD or null>"}
  ],
  "open_risks": [
    {"description": "<string>", "severity": "<low|medium|high|critical>",
     "owner": "<string or null>", "mitigation": "<string or null>"}
  ],
  "decisions_pending": [
    {"title": "<string>", "description": "<string>",
     "owner": "<string or null>", "due_date": "<YYYY-MM-DD or null>",
     "options": ["<string>", ...], "recommended": "<string or null>"}
  ]
}"""


class OrgNormalizerAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def normalize(
        self,
        raw_paste: Optional[str] = None,
        jira_data: Optional[dict] = None,
        linear_data: Optional[dict] = None,
        notion_data: Optional[dict] = None,
        slack_data: Optional[dict] = None,
        document_data: Optional[str] = None,
    ) -> OrgSnapshot:
        """
        Normalizes all available data sources into an OrgSnapshot.
        Structured API data is mapped first; LLM handles the rest.
        """
        if self.verbose:
            print("  [OrgNormalizer] Normalizing org data...")

        # Try structured normalization first
        structured = self._normalize_structured(jira_data, linear_data, notion_data)

        # Build raw text context for LLM
        raw_parts = []
        if raw_paste:
            raw_parts.append(f"=== Manual Input ===\n{raw_paste}")
        if document_data:
            raw_parts.append(f"=== Documents ===\n{document_data[:3000]}")
        if slack_data:
            raw_parts.append(f"=== Slack Messages ===\n{self._format_slack(slack_data)}")
        if structured:
            raw_parts.append(f"=== Structured Data (JSON) ===\n{json.dumps(structured, indent=2)[:4000]}")

        if not raw_parts:
            return OrgSnapshot(snapshot_date=date.today().isoformat())

        raw_text = "\n\n".join(raw_parts)
        return self._normalize_via_llm(raw_text)

    def _normalize_structured(
        self,
        jira_data: Optional[dict],
        linear_data: Optional[dict],
        notion_data: Optional[dict],
    ) -> Optional[dict]:
        """Map structured API data directly — no LLM needed."""
        if not any([jira_data, linear_data, notion_data]):
            return None

        teams: list[dict] = []

        if jira_data:
            for team_key, issues in jira_data.items():
                projects = []
                blockers = []
                for issue in issues:
                    status = self._map_jira_status(issue.get("fields", {}).get("status", {}).get("name", ""))
                    projects.append({
                        "name":         issue.get("fields", {}).get("summary", "")[:80],
                        "status":       status,
                        "owner":        (issue.get("fields", {}).get("assignee") or {}).get("displayName"),
                        "due_date":     issue.get("fields", {}).get("duedate"),
                        "blockers":     [],
                        "progress_pct": None,
                    })
                    if issue.get("fields", {}).get("priority", {}).get("name") == "Blocker":
                        blockers.append(issue.get("fields", {}).get("summary", ""))
                teams.append({
                    "vp_name":         team_key,
                    "team_name":       team_key,
                    "headcount":       0,
                    "active_projects": projects[:10],
                    "blockers":        blockers[:5],
                })

        if linear_data:
            for team_name, issues in linear_data.items():
                projects = []
                for issue in issues:
                    projects.append({
                        "name":   issue.get("title", "")[:80],
                        "status": self._map_linear_status(issue.get("state", {}).get("name", "")),
                        "owner":  (issue.get("assignee") or {}).get("name"),
                        "due_date": issue.get("dueDate"),
                        "blockers": [],
                        "progress_pct": None,
                    })
                teams.append({
                    "vp_name":         team_name,
                    "team_name":       team_name,
                    "headcount":       0,
                    "active_projects": projects[:10],
                    "blockers":        [],
                })

        initiatives = []
        risks = []
        if notion_data:
            for page in notion_data.get("pages", []):
                props = page.get("properties", {})
                name = self._get_notion_text(props, "Name") or self._get_notion_text(props, "Title")
                status = self._get_notion_text(props, "Status") or "active"
                item_type = self._get_notion_text(props, "Type") or "initiative"
                if item_type.lower() == "risk":
                    risks.append({"description": name, "severity": "medium"})
                else:
                    initiatives.append({"name": name, "description": "", "status": status.lower(), "teams_involved": []})

        return {
            "teams":               teams,
            "active_initiatives":  initiatives[:10],
            "open_risks":          risks[:10],
        }

    def _normalize_via_llm(self, raw_text: str) -> OrgSnapshot:
        prompt = (
            f"Normalize the following organizational data into a structured OrgSnapshot JSON.\n\n"
            f"{raw_text}\n\n"
            f"Use today's date ({date.today().isoformat()}) as snapshot_date.\n"
            f"Schema:\n{SNAPSHOT_SCHEMA}"
        )
        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        try:
            data = json.loads(raw)
            return OrgSnapshot(**data)
        except Exception as e:
            logger.warning(f"OrgNormalizer LLM parse failed: {e}")
            return OrgSnapshot(
                snapshot_date=date.today().isoformat(),
                raw_input=raw_text[:500],
            )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _map_jira_status(status: str) -> str:
        mapping = {
            "done": "completed", "closed": "completed",
            "in progress": "on_track", "in review": "on_track",
            "blocked": "blocked", "impediment": "blocked",
            "to do": "on_track", "open": "on_track",
        }
        return mapping.get(status.lower(), "on_track")

    @staticmethod
    def _map_linear_status(status: str) -> str:
        mapping = {
            "done": "completed", "completed": "completed", "cancelled": "completed",
            "in progress": "on_track", "in review": "on_track",
            "blocked": "blocked",
            "todo": "on_track", "backlog": "on_track",
        }
        return mapping.get(status.lower(), "on_track")

    @staticmethod
    def _get_notion_text(props: dict, key: str) -> Optional[str]:
        prop = props.get(key, {})
        if prop.get("type") == "title":
            items = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in items)
        if prop.get("type") == "rich_text":
            items = prop.get("rich_text", [])
            return "".join(t.get("plain_text", "") for t in items)
        if prop.get("type") == "select":
            return (prop.get("select") or {}).get("name")
        return None

    @staticmethod
    def _format_slack(slack_data: dict) -> str:
        lines = []
        for channel, messages in slack_data.items():
            lines.append(f"#{channel}:")
            for msg in messages[:10]:
                user = msg.get("username") or msg.get("user", "unknown")
                text = msg.get("text", "")[:200]
                lines.append(f"  [{user}]: {text}")
        return "\n".join(lines)
