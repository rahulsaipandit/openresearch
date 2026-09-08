"""
ComparisonAnalyst — compares two already-generated ResearchBriefs.

Runs after both StockResearchPipeline runs complete; does not re-fetch data,
it only reasons over the two structured briefs to produce a category-by-
category comparison (requirement #3: side-by-side comparison showing where
each stock excels).
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.comparison import ComparisonBrief, ComparisonVerdict
from schemas.stock import ResearchBrief

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a buy-side analyst comparing two stocks side by side.
You are given two structured research briefs. Compare them across Fundamentals,
Growth, Valuation, and Sentiment, and give an overall lean. Ground every
judgment in the numbers/text provided — do not invent data not present in the
briefs. Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

_SCHEMA = """{
  "overall_lean": "<ticker or 'Even'>",
  "summary": "<2-3 sentence executive summary of the comparison>",
  "categories": [
    {"category": "Fundamentals", "winner": "<ticker or 'Even'>", "rationale": "<1-2 sentences>"},
    {"category": "Growth", "winner": "<ticker or 'Even'>", "rationale": "<1-2 sentences>"},
    {"category": "Valuation", "winner": "<ticker or 'Even'>", "rationale": "<1-2 sentences>"},
    {"category": "Sentiment", "winner": "<ticker or 'Even'>", "rationale": "<1-2 sentences>"}
  ]
}"""


class ComparisonAnalystAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def compare(self, brief_a: ResearchBrief, brief_b: ResearchBrief) -> ComparisonBrief:
        if self.verbose:
            print(f"  [ComparisonAnalyst] Comparing {brief_a.ticker} vs {brief_b.ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(brief_a, brief_b)}],
            max_tokens=1200,
        )
        try:
            data = json.loads(raw)
            return ComparisonBrief(
                ticker_a=brief_a.ticker,
                ticker_b=brief_b.ticker,
                overall_lean=data.get("overall_lean", "Even"),
                summary=data.get("summary", ""),
                categories=[ComparisonVerdict(**c) for c in data.get("categories", [])],
                brief_a=brief_a,
                brief_b=brief_b,
            )
        except Exception as e:
            logger.warning(f"ComparisonAnalyst JSON parse failed: {e}\nRaw: {raw[:300]}")
            return self._fallback(brief_a, brief_b)

    def _build_prompt(self, a: ResearchBrief, b: ResearchBrief) -> str:
        def fmt(brief: ResearchBrief) -> str:
            return (
                f"Ticker: {brief.ticker} ({brief.company_name})\n"
                f"Verdict: {brief.verdict} | Price target: "
                f"${brief.price_target_low:.0f}-${brief.price_target_high:.0f}\n"
                f"Summary: {brief.summary}\n"
                f"Fundamentals: PE={brief.fundamentals.pe_ratio}, "
                f"ForwardPE={brief.fundamentals.forward_pe}, "
                f"RevGrowthYoY={brief.fundamentals.revenue_growth_yoy}, "
                f"ProfitMargin={brief.fundamentals.profit_margin}, "
                f"DebtToEquity={brief.fundamentals.debt_to_equity}\n"
                f"Bull case: {'; '.join(brief.bull_case)}\n"
                f"Bear case: {'; '.join(brief.bear_case)}\n"
                f"Sentiment: {brief.sentiment.tone} | "
                f"Catalysts: {'; '.join(brief.sentiment.catalysts)}\n"
            )

        return (
            f"=== Stock A ===\n{fmt(a)}\n=== Stock B ===\n{fmt(b)}\n\n"
            f"Produce a comparison JSON matching this schema:\n{_SCHEMA}"
        )

    def _fallback(self, a: ResearchBrief, b: ResearchBrief) -> ComparisonBrief:
        return ComparisonBrief(
            ticker_a=a.ticker,
            ticker_b=b.ticker,
            overall_lean="Even",
            summary="Comparison analysis unavailable — see individual briefs below.",
            categories=[],
            brief_a=a,
            brief_b=b,
        )
