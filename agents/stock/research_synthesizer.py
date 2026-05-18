"""
ResearchSynthesizer — Node 5 of the stock research pipeline.

LLM agent with a senior equity strategist persona.
Reads ValuationSummary + SentimentSummary and produces the final ResearchBrief.
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.stock import ResearchBrief, ValuationSummary, SentimentSummary

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior equity strategist writing a one-page research brief for a portfolio manager.
Your job is to synthesize fundamental analysis and market sentiment into a clear, actionable brief.

Guidelines:
- Be direct. The PM reads 50 briefs a week.
- Give a clear verdict with price target range.
- Bull case and bear case must be SPECIFIC — cite actual metrics or events, not generic statements.
- Acknowledge uncertainty honestly.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

BRIEF_SCHEMA = """{
  "ticker": "<string>",
  "company_name": "<string>",
  "as_of_date": "<YYYY-MM-DD>",
  "verdict": "<Strong Buy|Buy|Hold|Sell|Strong Sell>",
  "price_target_low": <float>,
  "price_target_high": <float>,
  "current_price": <float or null>,
  "summary": "<2-3 sentence executive summary>",
  "bull_case": ["<specific bull point>", "<specific bull point>", ...],
  "bear_case": ["<specific bear point>", "<specific bear point>", ...],
  "key_risks": ["<risk>", ...],
  "upcoming_catalysts": ["<earnings date>", "<product launch>", ...],
  "sources": ["<url or source name>", ...]
}"""


class ResearchSynthesizerAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def synthesize(
        self,
        ticker: str,
        price_data: dict,
        fundamentals: ValuationSummary,
        sentiment: SentimentSummary,
        news_data: dict,
    ) -> ResearchBrief:
        from datetime import date
        prompt = self._build_prompt(ticker, price_data, fundamentals, sentiment)

        if self.verbose:
            print(f"  [ResearchSynthesizer] Writing research brief for {ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )

        try:
            data = json.loads(raw)
            # Inject the sub-schemas
            data["fundamentals"] = fundamentals.model_dump()
            data["sentiment"]    = sentiment.model_dump()
            # Collect source URLs from news
            data.setdefault("sources", [
                h.get("url", "") for h in news_data.get("headlines", [])[:5]
                if h.get("url")
            ])
            return ResearchBrief(**data)
        except Exception as e:
            logger.warning(f"ResearchSynthesizer JSON parse failed: {e}\nRaw: {raw[:400]}")
            return self._fallback_brief(ticker, price_data, fundamentals, sentiment)

    def _build_prompt(
        self,
        ticker: str,
        price_data: dict,
        fundamentals: ValuationSummary,
        sentiment: SentimentSummary,
    ) -> str:
        from datetime import date
        lines = [
            f"Ticker: {ticker}",
            f"Company: {price_data.get('company_name', ticker)}",
            f"Date: {date.today().isoformat()}",
            "",
            "=== Fundamental Analysis ===",
            f"  Fair value range: ${fundamentals.fair_value_low:.2f} – ${fundamentals.fair_value_high:.2f}",
            f"  Current price: {f'${fundamentals.current_price:.2f}' if fundamentals.current_price else 'N/A'}",
            f"  P/E: {fundamentals.pe_ratio or 'N/A'}",
            f"  Forward P/E: {fundamentals.forward_pe or 'N/A'}",
            f"  Revenue growth: {f'{fundamentals.revenue_growth_yoy:.1%}' if fundamentals.revenue_growth_yoy else 'N/A'}",
            f"  Profit margin: {f'{fundamentals.profit_margin:.1%}' if fundamentals.profit_margin else 'N/A'}",
            f"  Moat: {fundamentals.moat_assessment}",
        ]

        if fundamentals.key_metrics:
            for k, v in list(fundamentals.key_metrics.items())[:6]:
                lines.append(f"  {k}: {v}")

        lines += [
            "",
            "=== Sentiment Analysis ===",
            f"  Tone: {sentiment.tone}",
            f"  Catalysts: {', '.join(sentiment.catalysts[:4]) or 'None identified'}",
            f"  Risks: {', '.join(sentiment.risks[:4]) or 'None identified'}",
        ]

        if sentiment.analyst_consensus:
            lines.append(f"  Analyst consensus: {sentiment.analyst_consensus}")

        if sentiment.sec_filings_summary:
            lines.append(f"  SEC filings: {sentiment.sec_filings_summary}")

        lines.append(f"\nWrite a ResearchBrief JSON matching this schema:\n{BRIEF_SCHEMA}")
        return "\n".join(lines)

    def _fallback_brief(
        self,
        ticker: str,
        price_data: dict,
        fundamentals: ValuationSummary,
        sentiment: SentimentSummary,
    ) -> ResearchBrief:
        from datetime import date
        return ResearchBrief(
            ticker=ticker,
            company_name=price_data.get("company_name", ticker),
            as_of_date=date.today().isoformat(),
            verdict="Hold",
            price_target_low=fundamentals.fair_value_low,
            price_target_high=fundamentals.fair_value_high,
            current_price=fundamentals.current_price,
            summary="Analysis pipeline encountered an error. Manual review required.",
            bull_case=sentiment.catalysts[:3],
            bear_case=sentiment.risks[:3],
            key_risks=sentiment.risks,
            upcoming_catalysts=[],
            fundamentals=fundamentals,
            sentiment=sentiment,
            sources=[],
        )
