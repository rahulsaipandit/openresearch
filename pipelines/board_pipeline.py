"""
Executive Board Pipeline

Multi-agent pipeline with parallel board member fan-out:

  DataIngestion
    → OrgNormalizer
    → [Board Members: parallel fan-out]
      chief_of_staff | vp_engineering | vp_product | vp_people | cto | cfo_proxy
    → ConflictDetector
    → CoSSynthesis
    → BoardBriefing
"""

import asyncio
import logging
from typing import Optional

from agents.api_utils import LLMClient
from agents.board.org_normalizer import OrgNormalizerAgent
from agents.board.chief_of_staff import ChiefOfStaffAgent
from agents.board.vp_engineering import VPEngineeringAgent
from agents.board.vp_product import VPProductAgent
from agents.board.vp_people import VPPeopleAgent
from agents.board.cto import CTOAgent
from agents.board.cfo_proxy import CFOProxyAgent
from agents.board.conflict_detector import ConflictDetectorAgent
from agents.board.cos_synthesis import CoSSynthesisAgent
from schemas.board import BoardBriefing, BoardSessionInput, OrgSnapshot, BoardMemberView

logger = logging.getLogger(__name__)

# All board member agent classes in order
BOARD_MEMBER_CLASSES = [
    ChiefOfStaffAgent,
    VPEngineeringAgent,
    VPProductAgent,
    VPPeopleAgent,
    CTOAgent,
    CFOProxyAgent,
]


class ExecutiveBoardPipeline:
    """
    Runs the full executive board pipeline.

    Usage:
        pipeline = ExecutiveBoardPipeline.from_config("config.yaml")
        briefing = await pipeline.run(BoardSessionInput(mode="weekly_review", raw_paste="..."))
    """

    def __init__(
        self,
        llm: LLMClient,
        board_members: Optional[list[str]] = None,
        parallel_execution: bool = True,
        verbose: bool = True,
    ):
        self.llm                = llm
        self.parallel_execution = parallel_execution
        self.verbose            = verbose

        enabled = set(board_members or [
            "chief_of_staff", "vp_engineering", "vp_product",
            "vp_people", "cto", "cfo_proxy"
        ])

        self.org_normalizer    = OrgNormalizerAgent(llm, verbose)
        self.board_agents      = [
            cls(llm, verbose) for cls in BOARD_MEMBER_CLASSES
            if cls.AGENT_ID in enabled
        ]
        self.conflict_detector = ConflictDetectorAgent(llm, verbose)
        self.cos_synthesis     = CoSSynthesisAgent(llm, verbose)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "ExecutiveBoardPipeline":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        llm       = LLMClient.from_config(config_path)
        board_cfg = cfg.get("executive_board", {})

        return cls(
            llm=llm,
            board_members=board_cfg.get("board_members"),
            parallel_execution=board_cfg.get("parallel_execution", True),
            verbose=True,
        )

    async def run(
        self,
        request: BoardSessionInput,
        jira_data: Optional[dict] = None,
        linear_data: Optional[dict] = None,
        notion_data: Optional[dict] = None,
        slack_data: Optional[dict] = None,
        document_data: Optional[str] = None,
    ) -> BoardBriefing:
        if self.verbose:
            print(f"\n[BoardPipeline] Starting {request.mode} session...")

        # Node 1: Normalize all inputs into OrgSnapshot
        if request.org_snapshot:
            snapshot = request.org_snapshot
            if self.verbose:
                print("  [1/4] Using pre-built OrgSnapshot")
        else:
            if self.verbose:
                print("  [1/4] Normalizing org data...")
            snapshot = self.org_normalizer.normalize(
                raw_paste=request.raw_paste,
                jira_data=jira_data,
                linear_data=linear_data,
                notion_data=notion_data,
                slack_data=slack_data,
                document_data=document_data,
            )

        # Node 2: Board member agents (parallel or sequential)
        if self.verbose:
            names = ", ".join(a.ROLE for a in self.board_agents)
            print(f"  [2/4] Running board members: {names}")

        if self.parallel_execution:
            board_views = await self._run_parallel(snapshot, request.mode)
        else:
            board_views = self._run_sequential(snapshot, request.mode)

        # Node 3: Conflict detection
        if self.verbose:
            print("  [3/4] Detecting cross-team conflicts...")
        conflict_report = self.conflict_detector.detect(board_views)

        # Node 4: Chief of Staff synthesis
        if self.verbose:
            print("  [4/4] Writing executive briefing...")
        briefing = self.cos_synthesis.synthesize(board_views, conflict_report, request.mode)

        if self.verbose:
            print(f"[BoardPipeline] Done. Org health: {briefing.org_health_score:.1f}/10 | "
                  f"Red flags: {len(briefing.red_flags)} | "
                  f"Action items: {len(briefing.action_items)}")

        return briefing

    async def _run_parallel(self, snapshot: OrgSnapshot, mode: str) -> list[BoardMemberView]:
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, agent.analyze, snapshot, mode)
            for agent in self.board_agents
        ]
        return list(await asyncio.gather(*tasks))

    def _run_sequential(self, snapshot: OrgSnapshot, mode: str) -> list[BoardMemberView]:
        return [agent.analyze(snapshot, mode) for agent in self.board_agents]
