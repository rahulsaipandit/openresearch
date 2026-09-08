"""
AdversarialReviewAgent — Research Primer section.

Stress-tests the existing bull/bear case by building the single strongest,
internally-consistent bear thesis (reconciling the debate map), flagging
where the bull case may be overstated, and running basic numeric sanity
checks against the stated price target. Loosely modeled on the "Adversarial
Review — Reconciliations, Integrated Bear Case, Numeric Audit" chapter of
institutional research primers.
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.primer import AdversarialReview, DebateItem, DriverTreeItem
from schemas.stock import ResearchBrief

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a skeptical senior analyst whose job is to stress-test a \
research brief before it goes to a portfolio manager. Build the single strongest, \
internally-consistent bear case by reconciling the debate map into one coherent \
narrative — do not just list bear points, integrate them. Flag specific places where \
the bull case or price target may be overstated. Run basic numeric sanity checks: \
does the implied upside/downside in the price target make sense given the stated \
fundamentals and risks? Be honest and specific — this is meant to catch problems, \
not rubber-stamp the existing brief.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

_SCHEMA = """{
  "integrated_bear_case": "<3-5 sentence coherent bear thesis, reconciling the debate map>",
  "reconciliation_notes": ["<specific place the bull case/price target may be overstated>", ...],
  "numeric_sanity_checks": ["<e.g. implied upside vs current price, checked against stated growth/margin assumptions>", ...]
}"""


class AdversarialReviewAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def review(
        self,
        brief: ResearchBrief,
        driver_tree: list[DriverTreeItem],
        debate_map: list[DebateItem],
    ) -> AdversarialReview:
        if self.verbose:
            print(f"  [AdversarialReview] Stress-testing bear case for {brief.ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(brief, driver_tree, debate_map)}],
            max_tokens=1200,
        )
        try:
            return AdversarialReview(**json.loads(raw))
        except Exception as e:
            logger.warning(f"AdversarialReview JSON parse failed: {e}\nRaw: {raw[:300]}")
            return self._fallback(brief)

    def _build_prompt(
        self, brief: ResearchBrief, driver_tree: list[DriverTreeItem], debate_map: list[DebateItem]
    ) -> str:
        lines = [
            f"Ticker: {brief.ticker} ({brief.company_name})",
            f"Verdict: {brief.verdict} | Price target: ${brief.price_target_low:.0f}-${brief.price_target_high:.0f}"
            f" | Current price: {brief.current_price if brief.current_price else 'N/A'}",
            f"Bear case: {'; '.join(brief.bear_case)}",
            f"Key risks: {'; '.join(brief.key_risks)}",
        ]
        if driver_tree:
            lines.append("\nDriver tree:")
            for d in driver_tree:
                lines.append(f"  [{d.direction}/{d.confidence}] {d.driver} — {d.note}")
        if debate_map:
            lines.append("\nDebate map:")
            for d in debate_map:
                lines.append(f"  Q: {d.question}\n    Bull: {d.bull_view}\n    Bear: {d.bear_view}")

        lines.append(f"\nProduce an AdversarialReview JSON matching this schema:\n{_SCHEMA}")
        return "\n".join(lines)

    def _fallback(self, brief: ResearchBrief) -> AdversarialReview:
        return AdversarialReview(
            integrated_bear_case="Adversarial review unavailable — see bear case in the underlying brief.",
            reconciliation_notes=[],
            numeric_sanity_checks=[],
        )
