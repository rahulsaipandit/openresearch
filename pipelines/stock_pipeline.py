"""
Stock Research Pipeline

Sequential 5-node pipeline:
  DataFetcher → NewsAggregator → FundamentalsAnalyst → SentimentAnalyst → ResearchSynthesizer

Each node reads from the pipeline state dict and writes its output back.
The final output is a ResearchBrief.
"""

import logging
from typing import Optional

from agents.api_utils import LLMClient
from agents.stock.data_fetcher import DataFetcherAgent
from agents.stock.news_aggregator import NewsAggregatorAgent
from agents.stock.fundamentals_analyst import FundamentalsAnalystAgent
from agents.stock.sentiment_analyst import SentimentAnalystAgent
from agents.stock.research_synthesizer import ResearchSynthesizerAgent
from schemas.stock import ResearchBrief, StockPipelineInput

logger = logging.getLogger(__name__)


class StockResearchPipeline:
    """
    Runs the full stock research pipeline for a given ticker.

    Usage:
        pipeline = StockResearchPipeline.from_config("config.yaml")
        brief = pipeline.run(StockPipelineInput(ticker="AAPL"))
    """

    def __init__(
        self,
        llm: LLMClient,
        alpha_vantage_key: str = "",
        polygon_key: str = "",
        news_api_key: str = "",
        verbose: bool = True,
    ):
        self.llm     = llm
        self.verbose = verbose

        self.data_fetcher    = DataFetcherAgent(
            alpha_vantage_key=alpha_vantage_key,
            polygon_key=polygon_key,
        )
        self.news_aggregator = NewsAggregatorAgent(news_api_key=news_api_key)
        self.fundamentals    = FundamentalsAnalystAgent(llm, verbose)
        self.sentiment       = SentimentAnalystAgent(llm, verbose)
        self.synthesizer     = ResearchSynthesizerAgent(llm, verbose)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "StockResearchPipeline":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        llm = LLMClient.from_config(config_path)
        stock_cfg = cfg.get("stock_research", {})
        sources   = stock_cfg.get("data_sources", {})

        return cls(
            llm=llm,
            alpha_vantage_key=sources.get("alpha_vantage_key", "") or "",
            polygon_key=sources.get("polygon_key", "") or "",
            news_api_key=sources.get("news_api_key", "") or "",
            verbose=cfg.get("server", {}).get("verbose", True),
        )

    def run(self, request: StockPipelineInput) -> ResearchBrief:
        ticker = request.ticker.upper().strip()
        depth  = request.depth

        if self.verbose:
            print(f"\n[StockPipeline] Starting research for {ticker} (depth={depth})")

        # Node 1: Fetch price + financials
        if self.verbose:
            print(f"  [1/5] Fetching market data...")
        raw_data = self.data_fetcher.fetch(ticker, depth=depth)
        price_data = raw_data.get("price_data", {})
        financials = raw_data.get("financials", {})

        # Node 2: Fetch news + SEC filings
        if self.verbose:
            print(f"  [2/5] Fetching news and filings...")
        company_name = price_data.get("company_name", ticker)
        news_data = self.news_aggregator.fetch(ticker, company_name=company_name, depth=depth)

        # Node 3: Fundamentals analysis (LLM)
        if self.verbose:
            print(f"  [3/5] Running fundamentals analysis...")
        valuation = self.fundamentals.analyze(ticker, price_data, financials)

        # Node 4: Sentiment analysis (LLM)
        if self.verbose:
            print(f"  [4/5] Running sentiment analysis...")
        sentiment = self.sentiment.analyze(ticker, news_data, price_data)

        # Node 5: Synthesis (LLM)
        if self.verbose:
            print(f"  [5/5] Synthesizing research brief...")
        brief = self.synthesizer.synthesize(
            ticker=ticker,
            price_data=price_data,
            fundamentals=valuation,
            sentiment=sentiment,
            news_data=news_data,
        )

        if self.verbose:
            print(f"[StockPipeline] Done. Verdict: {brief.verdict} | "
                  f"Target: ${brief.price_target_low:.0f}–${brief.price_target_high:.0f}")

        return brief
