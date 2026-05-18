"""
ConflictDetector — Node 8 of the Executive Board pipeline.

Reads all BoardMemberView outputs and finds:
  - Cross-agent disagreements (VP Eng says X, VP Product needs Y)
  - Resource contention between teams
  - Timeline clashes
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.board import BoardMemberView, ConflictReport, Conflict

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an organizational analyst specializing in conflict detection and
cross-functional alignment. Given the views from multiple board members, identify:

1. Disagreements: where two board members have contradictory assessments or incompatible needs
2. Resource contention: where multiple teams are competing for the same people, budget, or tooling
3. Timeline clashes: where one team's committed dates conflict with another's dependencies

Be specific — name the agents and the specific items in conflict.
Return ONLY valid JSON."""

REPORT_SCHEMA = """{
  "conflicts": [
    {
      "description": "<specific conflict description>",
      "parties": ["<agent_id_1>", "<agent_id_2>"],
      "severity": "<low|medium|high>",
      "suggested_resolution": "<string or null>"
    }
  ],
  "resource_contentions": ["<string describing contention>", ...],
  "timeline_clashes": ["<string describing clash>", ...],
  "summary": "<2-3 sentence overall conflict summary>"
}"""


class ConflictDetectorAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def detect(self, board_views: list[BoardMemberView]) -> ConflictReport:
        if self.verbose:
            print("  [ConflictDetector] Scanning for cross-team conflicts...")

        prompt = self._build_prompt(board_views)
        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )

        try:
            data = json.loads(raw)
            return ConflictReport(**data)
        except Exception as e:
            logger.warning(f"ConflictDetector JSON parse failed: {e}\nRaw: {raw[:300]}")
            return ConflictReport(summary="Conflict detection failed — manual review needed.")

    def _build_prompt(self, board_views: list[BoardMemberView]) -> str:
        lines = ["Board member views:"]
        for view in board_views:
            lines.append(f"\n=== {view.role} ({view.agent_id}) ===")
            if view.key_findings:
                lines.append("Key findings:")
                for f in view.key_findings:
                    lines.append(f"  - {f}")
            if view.risks:
                lines.append("Risks:")
                for r in view.risks:
                    lines.append(f"  - [{r.severity}] {r.description}")
            if view.recommendations:
                lines.append("Recommendations:")
                for r in view.recommendations[:3]:
                    lines.append(f"  - {r}")

        lines.append(f"\nIdentify conflicts and produce a ConflictReport JSON:\n{REPORT_SCHEMA}")
        return "\n".join(lines)
