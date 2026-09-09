"""
QueryRouterAgent — natural-language front door to the stock research pipeline.

Extracts intent + likely ticker(s) from a free-text query using a small LLM
call (a narrow classification/extraction task — a good fit for a local LM
Studio model per config.yaml's llm.provider_chain, reserving the heavier
provider for the fundamentals/sentiment/synthesis nodes), then verifies each
guessed ticker against yfinance before returning.

Never trusts an LLM-guessed ticker blindly: a small model can hallucinate a
ticker or guess the wrong exchange suffix (e.g. "Yes Bank" -> must resolve to
YESBANK.NS, not a US symbol). If a guess doesn't resolve, the caller gets a
clarification question back instead of a silently-wrong analysis.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from agents.api_utils import LLMClient, parse_llm_json
from schemas.query import CompanyGuess, QueryIntent, QueryRouterResult, ResolvedCompany

SYSTEM_PROMPT = """You are a financial query router. Given a user's natural-language \
question about stocks or companies, extract structured intent.

intent:
  - "single_analysis" — asking about one company/stock
  - "comparison" — asking to compare two companies/stocks
  - "watchlist_add" — asking to add a stock to a watchlist
  - "unknown" — not a stock/company question

For each company mentioned, guess its most likely stock ticker and exchange \
(e.g. "Reliance Industries" -> RELIANCE, NSE; "Yes Bank" -> YESBANK, NSE; \
"Apple" -> AAPL, NASDAQ). If unsure, leave likely_ticker null rather than \
guessing wildly.

Return ONLY valid JSON matching this schema — no prose, no markdown fences:
{
  "intent": "single_analysis" | "comparison" | "watchlist_add" | "unknown",
  "companies": [{"name": "<as mentioned>", "likely_ticker": "<ticker or null>", "exchange_guess": "<e.g. NASDAQ, NSE, or null>"}],
  "depth": "quick" | "full"
}"""

# Common non-US exchange suffixes to try when a bare ticker doesn't resolve on yfinance.
_EXCHANGE_SUFFIXES = {
    "NSE": ".NS",
    "BSE": ".BO",
    "LSE": ".L",
    "TSX": ".TO",
    "ASX": ".AX",
}


class QueryRouterAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def route(self, query: str) -> QueryRouterResult:
        intent = self._extract_intent(query)

        # Each _resolve_ticker() call is 1-2 blocking yfinance HTTP round
        # trips; a comparison query naming several companies used to
        # serialize all of them. They're independent, so resolve concurrently.
        resolved: list[ResolvedCompany] = []
        unresolved: list[str] = []
        if intent.companies:
            with ThreadPoolExecutor(max_workers=min(8, len(intent.companies))) as pool:
                tickers = list(pool.map(self._resolve_ticker, intent.companies))
            for company, ticker in zip(intent.companies, tickers):
                if ticker:
                    resolved.append(ResolvedCompany(name=company.name, ticker=ticker))
                else:
                    unresolved.append(company.name)

        if intent.intent == "unknown" or not intent.companies:
            return QueryRouterResult(
                intent="unknown",
                depth=intent.depth,
                clarification_needed=True,
                clarification_question=(
                    "I couldn't identify a company or stock in that question. "
                    "Try naming a specific company, e.g. "
                    "\"How are Reliance Industries' financials looking?\""
                ),
            )

        if unresolved:
            names = ", ".join(unresolved)
            return QueryRouterResult(
                intent=intent.intent,
                resolved=resolved,
                depth=intent.depth,
                clarification_needed=True,
                clarification_question=(
                    f"I couldn't find a ticker for: {names}. "
                    "Could you provide the exact ticker symbol and exchange?"
                ),
            )

        if intent.intent == "comparison" and len(resolved) < 2:
            return QueryRouterResult(
                intent=intent.intent,
                resolved=resolved,
                depth=intent.depth,
                clarification_needed=True,
                clarification_question=(
                    "A comparison needs two companies — which second company "
                    "should I compare against?"
                ),
            )

        return QueryRouterResult(
            intent=intent.intent,
            resolved=resolved,
            depth=intent.depth,
            clarification_needed=False,
        )

    # ── LLM extraction ────────────────────────────────────────────────────────

    def _extract_intent(self, query: str) -> QueryIntent:
        if self.verbose:
            print(f"  [QueryRouter] Routing query: {query!r}")
        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
            max_tokens=400,
        )
        return parse_llm_json(
            raw, "QueryRouter",
            builder=lambda data: QueryIntent(**data),
            fallback=lambda: self._fallback_intent(query),
        )

    # Common capitalized English words that would otherwise get matched by
    # the fallback regex ahead of a real ticker appearing later in the query
    # (e.g. "I think AAPL is undervalued" — re.search's leftmost match used
    # to pick "I" over "AAPL").
    _FALLBACK_STOPWORDS = {"I", "A"}

    def _fallback_intent(self, query: str) -> QueryIntent:
        """Regex fallback: look for a bare uppercase 1-5 letter token that looks like a ticker.

        Considers every match (not just the leftmost) and prefers the
        longest one, since a longer all-caps token is far more likely to be
        a genuine ticker than a stray capitalized word.
        """
        candidates = [
            m for m in re.findall(r"\b[A-Z]{1,5}\b", query) if m not in self._FALLBACK_STOPWORDS
        ]
        if candidates:
            token = max(candidates, key=len)
            return QueryIntent(
                intent="single_analysis",
                companies=[CompanyGuess(name=token, likely_ticker=token)],
            )
        return QueryIntent(intent="unknown")

    # ── Ticker verification (never trust the LLM guess blindly) ─────────────────

    def _resolve_ticker(self, company: CompanyGuess) -> Optional[str]:
        if not company.likely_ticker:
            return None

        candidates = [company.likely_ticker.upper().strip()]
        suffix = _EXCHANGE_SUFFIXES.get((company.exchange_guess or "").upper())
        if suffix and not candidates[0].endswith(suffix):
            candidates.append(f"{candidates[0]}{suffix}")

        for candidate in candidates:
            if self._ticker_exists(candidate):
                return candidate
        return None

    @staticmethod
    def _ticker_exists(ticker: str) -> bool:
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period="5d")
            return not hist.empty
        except Exception:
            return False
