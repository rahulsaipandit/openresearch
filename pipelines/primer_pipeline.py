"""
Research Primer Pipeline

Builds on the existing StockResearchPipeline rather than duplicating it:
  1. Run StockResearchPipeline -> ResearchBrief (baseload: fundamentals, sentiment, verdict)
  2. Run TrendAnalystAgent -> TrendData (baseload: 5yr trend)
  3. BusinessFoundationAgent -> deeper business/industry narrative
  4. DriverDebateAgent -> driver tree + debate map
  5. AdversarialReviewAgent -> integrated bear case + numeric sanity checks
  6. A short underwriting synthesis LLM call closes out the primer

This is the "middle ground" scope from requirements.md: richer than a single
ResearchBrief, but a single-pass pipeline rather than the full multi-day,
per-unknown deep-dive "20/60/20" process it's loosely modeled on.
"""

import json
import logging

from agents.api_utils import LLMClient
from agents.stock.business_foundation import BusinessFoundationAgent
from agents.stock.driver_debate import DriverDebateAgent
from agents.stock.adversarial_review import AdversarialReviewAgent
from agents.stock.trend_analyst import TrendAnalystAgent
from pipelines.stock_pipeline import StockResearchPipeline
from schemas.primer import PrimerPipelineInput, ResearchPrimer
from schemas.stock import StockPipelineInput

logger = logging.getLogger(__name__)

_UNDERWRITING_SYSTEM_PROMPT = """You are a senior equity strategist closing out a research \
primer. Write a short "underwriting chain" paragraph: connect the fundamentals, the \
strongest driver(s), the key debate(s), and the adversarial review into a coherent \
explanation of why the stated verdict and price target follow from the evidence — or \
where they don't fully hold up. 3-5 sentences. Plain text, not JSON."""


class ResearchPrimerPipeline:
    def __init__(self, llm: LLMClient, stock_pipeline: StockResearchPipeline, verbose: bool = True):
        self.llm             = llm
        self.stock_pipeline  = stock_pipeline
        self.trend_analyst   = TrendAnalystAgent()
        self.business        = BusinessFoundationAgent(llm, verbose)
        self.driver_debate    = DriverDebateAgent(llm, verbose)
        self.adversarial      = AdversarialReviewAgent(llm, verbose)
        self.verbose          = verbose

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "ResearchPrimerPipeline":
        llm = LLMClient.from_config(config_path)
        stock_pipeline = StockResearchPipeline.from_config(config_path)
        return cls(llm=llm, stock_pipeline=stock_pipeline)

    def run(self, request: PrimerPipelineInput) -> ResearchPrimer:
        ticker = request.ticker.upper().strip()

        if self.verbose:
            print(f"\n[PrimerPipeline] Building research primer for {ticker}...")
            print("  [1/6] Running baseline stock research pipeline...")
        brief = self.stock_pipeline.run(StockPipelineInput(ticker=ticker, depth=request.depth))

        if self.verbose:
            print("  [2/6] Fetching five-year trend data...")
        trend = self.trend_analyst.fetch(ticker)

        # Re-fetch the raw price/financials/news the stock pipeline already pulled,
        # so BusinessFoundation has real source material without a second full fetch.
        raw_data = self.stock_pipeline.data_fetcher.fetch(ticker, depth=request.depth)
        news_data = self.stock_pipeline.news_aggregator.fetch(
            ticker, company_name=brief.company_name, depth=request.depth
        )

        if self.verbose:
            print("  [3/6] Writing business foundation...")
        business = self.business.analyze(
            ticker, raw_data.get("price_data", {}), raw_data.get("financials", {}), news_data
        )

        if self.verbose:
            print("  [4/6] Building driver tree + debate map...")
        driver_tree, debate_map = self.driver_debate.analyze(brief)

        if self.verbose:
            print("  [5/6] Running adversarial review...")
        adversarial = self.adversarial.review(brief, driver_tree, debate_map)

        if self.verbose:
            print("  [6/6] Writing underwriting summary...")
        underwriting_summary = self._write_underwriting_summary(brief, driver_tree, debate_map, adversarial)

        if self.verbose:
            print(f"[PrimerPipeline] Done. {ticker}: {len(driver_tree)} drivers, "
                  f"{len(debate_map)} debates identified.")

        return ResearchPrimer(
            ticker=ticker,
            company_name=brief.company_name,
            as_of_date=brief.as_of_date,
            research_brief=brief,
            trend=trend,
            business_foundation=business,
            driver_tree=driver_tree,
            debate_map=debate_map,
            adversarial_review=adversarial,
            underwriting_summary=underwriting_summary,
        )

    def _write_underwriting_summary(self, brief, driver_tree, debate_map, adversarial) -> str:
        lines = [
            f"Verdict: {brief.verdict} | Price target: ${brief.price_target_low:.0f}-${brief.price_target_high:.0f}",
            f"Top drivers: {'; '.join(d.driver for d in driver_tree[:3])}",
            f"Key debates: {'; '.join(d.question for d in debate_map[:2])}",
            f"Integrated bear case: {adversarial.integrated_bear_case}",
        ]
        try:
            return self.llm.create(
                system=_UNDERWRITING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "\n".join(lines)}],
                max_tokens=400,
            ).strip()
        except Exception as e:
            logger.warning(f"Underwriting summary generation failed: {e}")
            return f"{brief.verdict} thesis rests on: {'; '.join(d.driver for d in driver_tree[:3]) or 'insufficient driver data'}."
