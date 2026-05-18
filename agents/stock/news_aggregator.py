"""
NewsAggregator — Node 2 of the stock research pipeline.

Fetches recent news and SEC filings for a ticker:
  - NewsAPI: last 30 days headlines (100 req/day free)
  - SEC EDGAR: recent 8-K and 10-Q filing summaries (free, no key)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K,10-Q"


class NewsAggregatorAgent:
    def __init__(self, news_api_key: str = ""):
        self.news_api_key = news_api_key

    def fetch(self, ticker: str, company_name: str = "", depth: str = "full") -> dict:
        """
        Returns:
          headlines: list of {title, source, published_at, url}
          sec_filings: list of {form, filed, description, url}
        """
        result: dict = {"headlines": [], "sec_filings": []}

        if self.news_api_key:
            result["headlines"] = self._fetch_newsapi(ticker, company_name)

        if depth == "full":
            result["sec_filings"] = self._fetch_edgar(ticker)

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

    # ── SEC EDGAR ──────────────────────────────────────────────────────────────

    def _fetch_edgar(self, ticker: str) -> list[dict]:
        since = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
        today = datetime.utcnow().strftime("%Y-%m-%d")

        try:
            with httpx.Client(timeout=15, headers={"User-Agent": "openresearch research@example.com"}) as client:
                # First resolve CIK from ticker
                cik = self._get_cik(client, ticker)
                if not cik:
                    return []

                r = client.get(
                    "https://data.sec.gov/submissions/",
                    params={},  # not used directly
                )
                # Use the EDGAR full-text search
                r2 = client.get(
                    f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
                )
                data = r2.json()
                filings = data.get("filings", {}).get("recent", {})
                forms       = filings.get("form", [])
                dates       = filings.get("filingDate", [])
                accessions  = filings.get("accessionNumber", [])
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
                    "company":   "",
                    "CIK":       ticker,
                    "type":      "",
                    "dateb":     "",
                    "owner":     "include",
                    "count":     "1",
                    "search_text": "",
                    "action":    "getcompany",
                    "output":    "atom",
                },
            )
            # Parse CIK from response — it appears as a 10-digit number
            import re
            match = re.search(r"CIK=(\d+)", r.text)
            if match:
                return match.group(1)
        except Exception as e:
            logger.debug(f"CIK lookup failed: {e}")
        return None
