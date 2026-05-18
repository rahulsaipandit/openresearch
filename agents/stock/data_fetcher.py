"""
DataFetcher — Node 1 of the stock research pipeline.

Fetches price, fundamentals, and financial statements from:
  - Yahoo Finance (yfinance) — free, no key required
  - Alpha Vantage — income statement, balance sheet (25 req/day free)
  - Polygon.io — earnings calendar, insider trades (5 req/min free)

Returns a dict of raw data consumed by the LLM analyst agents.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class DataFetcherAgent:
    def __init__(
        self,
        alpha_vantage_key: str = "",
        polygon_key: str = "",
    ):
        self.alpha_vantage_key = alpha_vantage_key
        self.polygon_key       = polygon_key

    def fetch(self, ticker: str, depth: str = "full") -> dict:
        """
        Fetch all available data for a ticker.

        Returns a dict with keys: price_data, financials, earnings, insider_trades.
        Missing sections are empty dicts — callers must handle gracefully.
        """
        ticker = ticker.upper().strip()
        result: dict = {
            "ticker": ticker,
            "price_data": {},
            "financials": {},
            "earnings": {},
            "insider_trades": [],
        }

        result["price_data"] = self._fetch_yahoo(ticker)

        if depth == "full":
            if self.alpha_vantage_key:
                result["financials"] = self._fetch_alpha_vantage(ticker)
            if self.polygon_key:
                result["earnings"]       = self._fetch_polygon_earnings(ticker)
                result["insider_trades"] = self._fetch_polygon_insiders(ticker)

        return result

    # ── Yahoo Finance ──────────────────────────────────────────────────────────

    def _fetch_yahoo(self, ticker: str) -> dict:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}

            return {
                "company_name":       info.get("longName", ticker),
                "sector":             info.get("sector", ""),
                "industry":           info.get("industry", ""),
                "current_price":      info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap":         info.get("marketCap"),
                "pe_ratio":           info.get("trailingPE"),
                "forward_pe":         info.get("forwardPE"),
                "eps":                info.get("trailingEps"),
                "revenue_growth":     info.get("revenueGrowth"),
                "profit_margin":      info.get("profitMargins"),
                "gross_margin":       info.get("grossMargins"),
                "debt_to_equity":     info.get("debtToEquity"),
                "free_cash_flow":     info.get("freeCashflow"),
                "52w_high":           info.get("fiftyTwoWeekHigh"),
                "52w_low":            info.get("fiftyTwoWeekLow"),
                "analyst_target":     info.get("targetMeanPrice"),
                "recommendation":     info.get("recommendationKey", ""),
                "short_ratio":        info.get("shortRatio"),
                "beta":               info.get("beta"),
                "dividend_yield":     info.get("dividendYield"),
                "business_summary":   info.get("longBusinessSummary", "")[:500],
            }
        except Exception as e:
            logger.warning(f"Yahoo Finance fetch failed for {ticker}: {e}")
            return {}

    # ── Alpha Vantage ──────────────────────────────────────────────────────────

    def _fetch_alpha_vantage(self, ticker: str) -> dict:
        base = "https://www.alphavantage.co/query"
        result: dict = {}

        try:
            with httpx.Client(timeout=15) as client:
                # Income statement
                r = client.get(base, params={
                    "function": "INCOME_STATEMENT",
                    "symbol": ticker,
                    "apikey": self.alpha_vantage_key,
                })
                data = r.json()
                annual = data.get("annualReports", [])
                if annual:
                    latest = annual[0]
                    result["income_statement"] = {
                        "fiscal_year":      latest.get("fiscalDateEnding"),
                        "total_revenue":    latest.get("totalRevenue"),
                        "gross_profit":     latest.get("grossProfit"),
                        "operating_income": latest.get("operatingIncome"),
                        "net_income":       latest.get("netIncome"),
                        "ebitda":           latest.get("ebitda"),
                        "eps":              latest.get("reportedEPS"),
                    }

                # Balance sheet
                r2 = client.get(base, params={
                    "function": "BALANCE_SHEET",
                    "symbol": ticker,
                    "apikey": self.alpha_vantage_key,
                })
                data2 = r2.json()
                annual2 = data2.get("annualReports", [])
                if annual2:
                    latest2 = annual2[0]
                    result["balance_sheet"] = {
                        "total_assets":       latest2.get("totalAssets"),
                        "total_liabilities":  latest2.get("totalLiabilities"),
                        "total_equity":       latest2.get("totalShareholderEquity"),
                        "cash":               latest2.get("cashAndCashEquivalentsAtCarryingValue"),
                        "long_term_debt":     latest2.get("longTermDebt"),
                    }
        except Exception as e:
            logger.warning(f"Alpha Vantage fetch failed for {ticker}: {e}")

        return result

    # ── Polygon.io ─────────────────────────────────────────────────────────────

    def _fetch_polygon_earnings(self, ticker: str) -> dict:
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    f"https://api.polygon.io/v3/reference/tickers/{ticker}/events",
                    params={"apiKey": self.polygon_key},
                )
                data = r.json()
                results = data.get("results", {}).get("events", [])
                earnings = [e for e in results if e.get("type") == "earnings_release_date"]
                return {"upcoming_earnings": earnings[:3]}
        except Exception as e:
            logger.warning(f"Polygon earnings fetch failed for {ticker}: {e}")
            return {}

    def _fetch_polygon_insiders(self, ticker: str) -> list:
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    "https://api.polygon.io/v2/reference/news",
                    params={
                        "ticker": ticker,
                        "limit": 5,
                        "apiKey": self.polygon_key,
                    },
                )
                data = r.json()
                return data.get("results", [])
        except Exception as e:
            logger.warning(f"Polygon insider fetch failed for {ticker}: {e}")
            return []
