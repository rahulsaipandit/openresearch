"""
FundamentalsAnalyst — Node 3 of the stock research pipeline.

LLM agent with a buy-side fundamental analyst persona.
Reads raw price/financial data and produces a structured ValuationSummary.
"""

import json
import logging
from typing import Optional

from agents.api_utils import LLMClient
from schemas.stock import ValuationSummary

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a buy-side fundamental analyst at a top-tier investment fund.
You specialize in equity valuation using DCF, comparable company analysis, and financial
statement analysis. You are rigorous, data-driven, and intellectually honest about uncertainty.

Given raw financial data for a stock, produce a structured valuation assessment.
Always ground your analysis in the provided numbers. Acknowledge when data is missing.
Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

VALUATION_SCHEMA = """{
  "fair_value_low": <float — conservative DCF / comps low end>,
  "fair_value_high": <float — bull case high end>,
  "current_price": <float or null>,
  "pe_ratio": <float or null>,
  "forward_pe": <float or null>,
  "eps": <float or null>,
  "revenue_growth_yoy": <float or null — decimal, e.g. 0.12 for 12%>,
  "profit_margin": <float or null — decimal>,
  "debt_to_equity": <float or null>,
  "market_cap": <float or null>,
  "moat_assessment": "<string — competitive moat analysis, 2-3 sentences>",
  "key_metrics": {
    "<metric_name>": "<value with unit>",
    ...
  }
}"""


class FundamentalsAnalystAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def analyze(self, ticker: str, price_data: dict, financials: dict) -> ValuationSummary:
        prompt = self._build_prompt(ticker, price_data, financials)
        if self.verbose:
            print(f"  [FundamentalsAnalyst] Analyzing {ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )

        try:
            data = json.loads(raw)
            return ValuationSummary(**data)
        except Exception as e:
            logger.warning(f"FundamentalsAnalyst JSON parse failed: {e}\nRaw: {raw[:300]}")
            return self._fallback_summary(price_data)

    def _build_prompt(self, ticker: str, price_data: dict, financials: dict) -> str:
        lines = [f"Ticker: {ticker}"]
        lines.append(f"Company: {price_data.get('company_name', ticker)}")
        lines.append(f"Sector: {price_data.get('sector', 'N/A')} / {price_data.get('industry', 'N/A')}")
        lines.append("")
        lines.append("=== Market Data ===")
        for k in ["current_price", "market_cap", "pe_ratio", "forward_pe", "eps",
                  "revenue_growth", "profit_margin", "debt_to_equity", "beta",
                  "52w_high", "52w_low", "analyst_target", "recommendation"]:
            v = price_data.get(k)
            if v is not None:
                lines.append(f"  {k}: {v}")

        if financials.get("income_statement"):
            lines.append("\n=== Income Statement (Latest Annual) ===")
            for k, v in financials["income_statement"].items():
                if v is not None:
                    lines.append(f"  {k}: {v}")

        if financials.get("balance_sheet"):
            lines.append("\n=== Balance Sheet ===")
            for k, v in financials["balance_sheet"].items():
                if v is not None:
                    lines.append(f"  {k}: {v}")

        if price_data.get("business_summary"):
            lines.append(f"\nBusiness: {price_data['business_summary']}")

        lines.append(f"\nProduce a ValuationSummary JSON matching this schema:\n{VALUATION_SCHEMA}")
        return "\n".join(lines)

    def _fallback_summary(self, price_data: dict) -> ValuationSummary:
        price = price_data.get("current_price") or 0.0
        return ValuationSummary(
            fair_value_low=price * 0.85,
            fair_value_high=price * 1.15,
            current_price=price,
            pe_ratio=price_data.get("pe_ratio"),
            forward_pe=price_data.get("forward_pe"),
            eps=price_data.get("eps"),
            moat_assessment="Insufficient data for moat assessment.",
            key_metrics={},
        )
