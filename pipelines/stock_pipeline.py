"""
Stock Research Pipeline

Sequential 5-node pipeline:
  DataFetcher → NewsAggregator → FundamentalsAnalyst → SentimentAnalyst → ResearchSynthesizer

Each node reads from the pipeline state dict and writes its output back.
The final output is a ResearchBrief.

When Equibles is running (mcp.equibles.enabled: true in config.yaml), Nodes 1 and 2
are automatically enriched with:
  - Node 1 (DataFetcher):   13F institutional holdings, FINRA short interest,
                             SEC fails-to-deliver, technical indicators,
                             congressional trading disclosures
  - Node 2 (NewsAggregator): SEC full-text excerpts (risk factors, guidance, MD&A),
                             Form 3/4 insider transactions

The Equibles data is injected into the LLM prompt in Node 5 (ResearchSynthesizer)
so the final brief cites real ownership changes, short pressure, and insider signals.
It is also attached to the returned ResearchBrief as typed optional sub-schemas.

All Equibles calls are gated + fail silently — the pipeline always completes even
when Equibles is not running.
"""

import logging
from typing import Optional

from agents.api_utils import LLMClient
from agents.mcp_client import MCPClient
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
        mcp: MCPClient | None = None,
        verbose: bool = True,
    ):
        self.llm     = llm
        self.mcp     = mcp
        self.verbose = verbose

        self.data_fetcher    = DataFetcherAgent(
            alpha_vantage_key=alpha_vantage_key,
            polygon_key=polygon_key,
            mcp=mcp,
        )
        self.news_aggregator = NewsAggregatorAgent(
            news_api_key=news_api_key,
            mcp=mcp,
        )
        self.fundamentals    = FundamentalsAnalystAgent(llm, verbose)
        self.sentiment       = SentimentAnalystAgent(llm, verbose)
        self.synthesizer     = ResearchSynthesizerAgent(llm, verbose)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "StockResearchPipeline":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        llm      = LLMClient.from_config(config_path)
        mcp      = MCPClient.from_config(config_path)
        stock_cfg = cfg.get("stock_research", {})
        sources   = stock_cfg.get("data_sources", {})

        equibles_enabled = (
            cfg.get("mcp", {}).get("equibles", {}).get("enabled", False)
        )
        if equibles_enabled and mcp.is_available("equibles"):
            logger.info("StockResearchPipeline: Equibles MCP server enabled — "
                        "institutional, short interest, insider, and technical data active")

        return cls(
            llm=llm,
            alpha_vantage_key=sources.get("alpha_vantage_key", "") or "",
            polygon_key=sources.get("polygon_key", "") or "",
            news_api_key=sources.get("news_api_key", "") or "",
            mcp=mcp,
            verbose=cfg.get("server", {}).get("verbose", True),
        )

    def run(self, request: StockPipelineInput) -> ResearchBrief:
        ticker = request.ticker.upper().strip()
        depth  = request.depth

        equibles_active = self.mcp and self.mcp.is_available("equibles")

        if self.verbose:
            equibles_note = " + Equibles" if equibles_active else ""
            print(f"\n[StockPipeline] Starting research for {ticker} "
                  f"(depth={depth}{equibles_note})")

        # ── Node 1: Fetch price + financials (+ Equibles market structure) ───
        if self.verbose:
            print(f"  [1/5] Fetching market data"
                  f"{' + institutional/short/technical data' if equibles_active else ''}...")
        raw_data = self.data_fetcher.fetch(ticker, depth=depth)

        price_data           = raw_data.get("price_data", {})
        financials           = raw_data.get("financials", {})
        institutional_raw    = raw_data.get("institutional")     # None if Equibles not running
        market_structure_raw = raw_data.get("market_structure")  # None if Equibles not running
        technicals_raw       = raw_data.get("technicals")        # None if Equibles not running

        # ── Node 2: Fetch news + SEC filings (+ Equibles full-text + insiders) ──
        if self.verbose:
            print(f"  [2/5] Fetching news and filings"
                  f"{' + SEC full-text excerpts + insider trades' if equibles_active else ''}...")
        company_name = price_data.get("company_name", ticker)
        news_data = self.news_aggregator.fetch(ticker, company_name=company_name, depth=depth)

        # ── Node 3: Fundamentals analysis (LLM) ──────────────────────────────
        if self.verbose:
            print(f"  [3/5] Running fundamentals analysis...")
        valuation = self.fundamentals.analyze(ticker, price_data, financials)

        # ── Node 4: Sentiment analysis (LLM) ─────────────────────────────────
        if self.verbose:
            print(f"  [4/5] Running sentiment analysis...")
        sentiment = self.sentiment.analyze(ticker, news_data, price_data)

        # ── Node 5: Synthesis (LLM) — all signals combined ───────────────────
        if self.verbose:
            print(f"  [5/5] Synthesizing research brief"
                  f"{' (with Equibles signals)' if equibles_active else ''}...")
        brief = self.synthesizer.synthesize(
            ticker=ticker,
            price_data=price_data,
            fundamentals=valuation,
            sentiment=sentiment,
            news_data=news_data,
            institutional_raw=institutional_raw,
            market_structure_raw=market_structure_raw,
            technicals_raw=technicals_raw,
        )

        if self.verbose:
            equibles_status = (
                " | Equibles: institutional ✓ short ✓ technicals ✓"
                if (institutional_raw and market_structure_raw and technicals_raw)
                else (" | Equibles: partial data" if equibles_active else " | Equibles: off")
            )
            print(f"[StockPipeline] Done. Verdict: {brief.verdict} | "
                  f"Target: ${brief.price_target_low:.0f}–${brief.price_target_high:.0f}"
                  f"{equibles_status}")

        return brief
