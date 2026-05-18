"""
SentimentAnalyst — Node 4 of the stock research pipeline.

LLM agent with a news-driven equity researcher persona.
Reads news headlines and SEC filings and produces a SentimentSummary.
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.stock import SentimentSummary

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a news-driven equity researcher specializing in market sentiment analysis.
You read earnings call transcripts, news, and SEC filings to identify market catalysts, risks,
and the prevailing narrative around a stock.

Given recent headlines and SEC filing information, produce a structured sentiment assessment.
Be specific — cite actual headlines or filing details when possible.
Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

SENTIMENT_SCHEMA = """{
  "tone": "<bullish|neutral|bearish>",
  "catalysts": ["<specific positive catalyst>", ...],
  "risks": ["<specific risk or concern>", ...],
  "analyst_consensus": "<string summarizing analyst sentiment, or null>",
  "recent_headlines": ["<verbatim or paraphrased headline>", ...],
  "sec_filings_summary": "<string — 2-3 sentence summary of recent 8-K/10-Q themes, or null>"
}"""


class SentimentAnalystAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def analyze(self, ticker: str, news_data: dict, price_data: dict) -> SentimentSummary:
        prompt = self._build_prompt(ticker, news_data, price_data)
        if self.verbose:
            print(f"  [SentimentAnalyst] Analyzing {ticker} news...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
        )

        try:
            data = json.loads(raw)
            return SentimentSummary(**data)
        except Exception as e:
            logger.warning(f"SentimentAnalyst JSON parse failed: {e}\nRaw: {raw[:300]}")
            return SentimentSummary(
                tone="neutral",
                catalysts=[],
                risks=["Unable to parse sentiment analysis"],
                recent_headlines=[h.get("title", "") for h in news_data.get("headlines", [])[:5]],
            )

    def _build_prompt(self, ticker: str, news_data: dict, price_data: dict) -> str:
        lines = [f"Ticker: {ticker}"]
        lines.append(f"Company: {price_data.get('company_name', ticker)}")

        analyst_rec = price_data.get("recommendation", "")
        analyst_target = price_data.get("analyst_target")
        if analyst_rec:
            lines.append(f"Analyst consensus: {analyst_rec}" +
                         (f" (target: ${analyst_target:.2f})" if analyst_target else ""))

        headlines = news_data.get("headlines", [])
        if headlines:
            lines.append(f"\n=== Recent Headlines (last 30 days) ===")
            for h in headlines[:15]:
                lines.append(f"  [{h.get('source', '')} | {h.get('published_at', '')[:10]}] {h.get('title', '')}")
                if h.get("description"):
                    lines.append(f"    {h['description'][:150]}")

        filings = news_data.get("sec_filings", [])
        if filings:
            lines.append(f"\n=== Recent SEC Filings ===")
            for f in filings[:5]:
                lines.append(f"  {f.get('form', '')} filed {f.get('filed', '')} — {f.get('description', '')}")

        lines.append(f"\nProduce a SentimentSummary JSON matching this schema:\n{SENTIMENT_SCHEMA}")
        return "\n".join(lines)
