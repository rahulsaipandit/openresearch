"""
BusinessFoundationAgent — Research Primer section.

LLM agent producing a deeper company/industry narrative than the fundamentals
node covers: business model mechanics, revenue segments, and unit economics
in plain language. Loosely modeled on the "Business Foundation" chapter of
institutional research primers (see Initial_requirement_collection.md), but
a single-pass LLM synthesis rather than a multi-source deep-dive investigation.
"""

from agents.api_utils import LLMClient, parse_llm_json
from schemas.primer import BusinessFoundation

SYSTEM_PROMPT = """You are an equity research associate writing the "Business Foundation" \
section of an institutional research primer. Describe the company's business model, \
revenue segments, and unit economics in plain, factual language — no valuation opinions, \
no price targets, no buy/sell language. Ground every claim in the data provided; if \
something isn't in the data, say so rather than inventing detail.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

_SCHEMA = """{
  "overview": "<2-4 sentences: what the company does, how it's structured>",
  "revenue_model": "<2-4 sentences: how revenue is actually generated>",
  "key_segments": ["<segment/product line>", ...],
  "unit_economics_notes": "<1-3 sentences on margins, cost structure, or customer economics if inferable from the data>"
}"""


class BusinessFoundationAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def analyze(self, ticker: str, price_data: dict, financials: dict, news_data: dict) -> BusinessFoundation:
        if self.verbose:
            print(f"  [BusinessFoundation] Writing business foundation for {ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(ticker, price_data, financials, news_data)}],
            max_tokens=900,
        )
        return parse_llm_json(
            raw, "BusinessFoundation",
            builder=lambda data: BusinessFoundation(**data),
            fallback=lambda: self._fallback(price_data),
        )

    def _build_prompt(self, ticker: str, price_data: dict, financials: dict, news_data: dict) -> str:
        lines = [
            f"Ticker: {ticker}",
            f"Company: {price_data.get('company_name', ticker)}",
            f"Sector: {price_data.get('sector', 'N/A')} / {price_data.get('industry', 'N/A')}",
        ]
        if price_data.get("business_summary"):
            lines.append(f"Business summary: {price_data['business_summary']}")
        if financials.get("income_statement"):
            lines.append("\nIncome statement (latest annual):")
            for k, v in financials["income_statement"].items():
                if v is not None:
                    lines.append(f"  {k}: {v}")
        filings_summary = news_data.get("sec_filings_summary") or news_data.get("filings_summary")
        if filings_summary:
            lines.append(f"\nRecent SEC filings summary: {filings_summary}")

        lines.append(f"\nProduce a BusinessFoundation JSON matching this schema:\n{_SCHEMA}")
        return "\n".join(lines)

    def _fallback(self, price_data: dict) -> BusinessFoundation:
        return BusinessFoundation(
            overview=price_data.get("business_summary", "") or "Insufficient data for a business overview.",
            revenue_model="Insufficient data to describe the revenue model.",
            key_segments=[],
            unit_economics_notes="",
        )
