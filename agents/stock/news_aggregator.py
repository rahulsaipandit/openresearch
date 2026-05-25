"""
NewsAggregator — Node 2 of the stock research pipeline.

Fetches recent news and SEC filings for a ticker from:
  - NewsAPI                           — last 30 days headlines (100 req/day free)
  - SEC EDGAR                         — recent 8-K / 10-Q / 10-K filing index (free, no key)
  - Equibles (self-hosted MCP server) — SEC full-text search (relevant excerpts, not just
                                        filing metadata) + SEC Form 3/4 insider transactions
                                        (requires `docker compose up` in the Equibles repo)

When Equibles is available, it augments rather than replaces the existing EDGAR index
fetch — you get both the filing list (EDGAR) and relevant excerpts from inside the
documents (Equibles full-text search). Insider transactions from Equibles also move
to this node since they are narrative/context data, not price/structure data.

All Equibles calls are gated behind mcp.is_available("equibles") and fail silently.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class NewsAggregatorAgent:
    def __init__(
        self,
        news_api_key: str = "",
        mcp=None,               # MCPClient | None — injected by pipeline
    ):
        self.news_api_key = news_api_key
        self.mcp          = mcp

    def fetch(self, ticker: str, company_name: str = "", depth: str = "full") -> dict:
        """
        Returns:
          headlines       — list of {title, source, published_at, url, description}
          sec_filings     — list of {form, filed, description, url, accession}
          sec_excerpts    — list of {form, filed, query, excerpt, url}  [Equibles, depth=full]
          insider_trades  — list of {name, title, type, shares, price, value, date, form}
                            [Equibles, depth=full; replaces the old Polygon insider call]
        """
        result: dict = {
            "headlines":      [],
            "sec_filings":    [],
            "sec_excerpts":   [],   # Equibles full-text excerpts — empty when not available
            "insider_trades": [],   # Equibles Form 3/4 — empty when not available
        }

        if self.news_api_key:
            result["headlines"] = self._fetch_newsapi(ticker, company_name)

        if depth == "full":
            result["sec_filings"] = self._fetch_edgar(ticker)

            if self.mcp and self.mcp.is_available("equibles"):
                result["sec_excerpts"]   = self._fetch_equibles_sec_excerpts(ticker)
                result["insider_trades"] = self._fetch_equibles_insiders(ticker)

        return result

    # ── NewsAPI ────────────────────────────────────────────────────────────────

    def _fetch_newsapi(self, ticker: str, company_name: str) -> list[dict]:
        query = company_name if company_name else ticker
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q":        f'"{query}" OR "{ticker}"',
                        "from":     since,
                        "sortBy":   "relevancy",
                        "language": "en",
                        "pageSize": 20,
                        "apiKey":   self.news_api_key,
                    },
                )
                data = r.json()
                articles = data.get("articles", [])
                return [
                    {
                        "title":        a.get("title", ""),
                        "source":       a.get("source", {}).get("name", ""),
                        "published_at": a.get("publishedAt", ""),
                        "url":          a.get("url", ""),
                        "description":  a.get("description", ""),
                    }
                    for a in articles
                    if a.get("title") and "[Removed]" not in a.get("title", "")
                ]
        except Exception as e:
            logger.warning(f"NewsAPI fetch failed for {ticker}: {e}")
            return []

    # ── SEC EDGAR (filing index) ───────────────────────────────────────────────

    def _fetch_edgar(self, ticker: str) -> list[dict]:
        """
        Fetch recent 8-K / 10-Q / 10-K filing metadata from SEC EDGAR.
        Returns filing index entries (form type, date, accession number, primary doc URL).
        When Equibles is also available, _fetch_equibles_sec_excerpts() adds the actual
        text content of the most relevant passages from these same filings.
        """
        since = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")

        try:
            with httpx.Client(
                timeout=15,
                headers={"User-Agent": "openresearch research@example.com"},
            ) as client:
                cik = self._get_cik(client, ticker)
                if not cik:
                    return []

                r = client.get(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json")
                data = r.json()
                filings      = data.get("filings", {}).get("recent", {})
                forms        = filings.get("form", [])
                dates        = filings.get("filingDate", [])
                accessions   = filings.get("accessionNumber", [])
                descriptions = filings.get("primaryDocument", [])

                results = []
                for form, date, acc, desc in zip(forms, dates, accessions, descriptions):
                    if form not in ("8-K", "10-Q", "10-K"):
                        continue
                    if date < since:
                        continue
                    acc_clean = acc.replace("-", "")
                    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{desc}"
                    results.append({
                        "form":        form,
                        "filed":       date,
                        "description": desc,
                        "url":         url,
                        "accession":   acc,
                    })
                    if len(results) >= 10:
                        break

                return results

        except Exception as e:
            logger.warning(f"SEC EDGAR fetch failed for {ticker}: {e}")
            return []

    def _get_cik(self, client: httpx.Client, ticker: str) -> Optional[str]:
        try:
            r = client.get(
                "https://www.sec.gov/cgi-bin/browse-edgar",
                params={
                    "company":      "",
                    "CIK":          ticker,
                    "type":         "",
                    "dateb":        "",
                    "owner":        "include",
                    "count":        "1",
                    "search_text":  "",
                    "action":       "getcompany",
                    "output":       "atom",
                },
            )
            import re
            match = re.search(r"CIK=(\d+)", r.text)
            if match:
                return match.group(1)
        except Exception as e:
            logger.debug(f"CIK lookup failed: {e}")
        return None

    # ── Equibles: SEC full-text search ────────────────────────────────────────

    def _fetch_equibles_sec_excerpts(self, ticker: str) -> list[dict]:
        """
        Run targeted full-text searches against the Equibles SEC filing index.
        Returns excerpts from risk factors, revenue guidance, and management commentary
        — the parts of 10-K/10-Q/8-K filings that EDGAR metadata doesn't surface.
        """
        queries = [
            ("risk factors supply chain competition",       ["10-K", "10-Q"]),
            ("revenue guidance outlook forward-looking",    ["10-K", "10-Q", "8-K"]),
            ("management discussion results operations",    ["10-K", "10-Q"]),
        ]

        excerpts = []
        for query, forms in queries:
            raw = self.mcp.equibles_search_sec_filings(
                ticker,
                query=query,
                forms=forms,
                max_results=3,
            )
            if not raw:
                continue
            for item in raw:
                excerpt_text = (
                    item.get("excerpt")
                    or item.get("text")
                    or item.get("content")
                    or item.get("snippet")
                    or ""
                )
                if not excerpt_text:
                    continue
                excerpts.append({
                    "form":    item.get("form") or item.get("formType") or "",
                    "filed":   item.get("filedDate") or item.get("filed") or item.get("date") or "",
                    "query":   query,
                    "excerpt": excerpt_text[:800],   # cap per-excerpt for prompt budget
                    "url":     item.get("url") or item.get("filingUrl") or "",
                })
            if len(excerpts) >= 9:   # 3 queries × 3 results — enough context
                break

        return excerpts

    # ── Equibles: insider transactions ────────────────────────────────────────

    def _fetch_equibles_insiders(self, ticker: str) -> list[dict]:
        """
        Fetch recent SEC Form 3/4 insider transactions from Equibles.
        Returns normalised list of buy/sell records for the past 90 days.
        """
        raw = self.mcp.equibles_insider_transactions(ticker, days=90)
        if not raw:
            return []

        normalised = []
        for t in raw[:15]:    # cap at 15 transactions for prompt budget
            normalised.append({
                "name":  t.get("insiderName") or t.get("name") or t.get("filerName") or "",
                "title": t.get("title") or t.get("relationship") or t.get("officerTitle") or "",
                "type":  t.get("transactionType") or t.get("type") or t.get("acquisitionOrDisposition") or "",
                "shares":           t.get("shares") or t.get("sharesTraded"),
                "price_per_share":  t.get("pricePerShare") or t.get("price"),
                "total_value":      t.get("totalValue") or t.get("value"),
                "date":             t.get("transactionDate") or t.get("date") or t.get("filingDate") or "",
                "form":             t.get("formType") or t.get("form") or "",
            })

        return normalised
