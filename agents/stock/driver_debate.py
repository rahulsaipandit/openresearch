"""
DriverDebateAgent — Research Primer section.

Produces a driver tree (key value drivers, tailwind/headwind, confidence) and
a debate map (the open questions the bull and bear cases actually disagree
about) from the already-generated ResearchBrief. Loosely modeled on the
"Baseload Compile — Driver Tree, Debate Map, Unknowns Inventory" chapter of
institutional research primers, scoped to a single LLM pass rather than a
per-unknown deep-dive investigation (see requirements.md scoping decision).
"""

from agents.api_utils import LLMClient, parse_llm_json
from schemas.primer import DebateItem, DriverTreeItem
from schemas.stock import ResearchBrief

SYSTEM_PROMPT = """You are an equity research associate building a "driver tree" and \
"debate map" for a stock. The driver tree lists the concrete factors that will move \
the stock's value (tailwinds and headwinds), each with a confidence level. The debate \
map lists the specific open questions where the bull and bear cases genuinely disagree \
— not generic risks, but points of real interpretive disagreement about the same data. \
Ground everything in the bull case, bear case, risks, and catalysts provided — do not \
invent drivers or debates not implied by that material.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

_SCHEMA = """{
  "driver_tree": [
    {"driver": "<specific driver>", "direction": "tailwind"|"headwind"|"mixed", "confidence": "high"|"medium"|"low", "note": "<1 sentence>"}
  ],
  "debate_map": [
    {"question": "<the specific disagreement>", "bull_view": "<1-2 sentences>", "bear_view": "<1-2 sentences>", "what_would_resolve_it": "<specific data/event that would settle it>"}
  ]
}"""


class DriverDebateAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def analyze(self, brief: ResearchBrief) -> tuple[list[DriverTreeItem], list[DebateItem]]:
        if self.verbose:
            print(f"  [DriverDebate] Building driver tree + debate map for {brief.ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(brief)}],
            max_tokens=1200,
        )
        def _build(data: dict) -> tuple[list[DriverTreeItem], list[DebateItem]]:
            drivers = [DriverTreeItem(**d) for d in data.get("driver_tree", [])]
            debates = [DebateItem(**d) for d in data.get("debate_map", [])]
            return drivers, debates

        return parse_llm_json(
            raw, "DriverDebate",
            builder=_build,
            fallback=lambda: self._fallback(brief),
        )

    def _build_prompt(self, brief: ResearchBrief) -> str:
        lines = [
            f"Ticker: {brief.ticker} ({brief.company_name})",
            f"Verdict: {brief.verdict}",
            f"Summary: {brief.summary}",
            f"Bull case: {'; '.join(brief.bull_case)}",
            f"Bear case: {'; '.join(brief.bear_case)}",
            f"Key risks: {'; '.join(brief.key_risks)}",
            f"Upcoming catalysts: {'; '.join(brief.upcoming_catalysts)}",
            f"\nProduce driver_tree + debate_map JSON matching this schema:\n{_SCHEMA}",
        ]
        return "\n".join(lines)

    def _fallback(self, brief: ResearchBrief) -> tuple[list[DriverTreeItem], list[DebateItem]]:
        drivers = [
            DriverTreeItem(driver=b, direction="tailwind", confidence="low", note="From bull case (fallback).")
            for b in brief.bull_case[:3]
        ] + [
            DriverTreeItem(driver=b, direction="headwind", confidence="low", note="From bear case (fallback).")
            for b in brief.bear_case[:3]
        ]
        return drivers, []
