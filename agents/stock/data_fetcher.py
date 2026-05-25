"""
DataFetcher — Node 1 of the stock research pipeline.

Fetches price, fundamentals, and market structure data from:
  - Yahoo Finance (yfinance)          — free, no key required
  - Alpha Vantage                     — income statement, balance sheet (25 req/day free)
  - Polygon.io                        — earnings calendar (5 req/min free)
  - Equibles (self-hosted MCP server) — 13F institutional holdings, FINRA short interest,
                                        SEC fails-to-deliver, technical indicators,
                                        congressional trading disclosures
                                        (requires `docker compose up` in the Equibles repo)

Returns a dict of raw data consumed by the LLM analyst agents (Nodes 3–5).

Equibles data is optional — all Equibles calls are gated behind
mcp.is_available("equibles") and fail silently on error. The pipeline always
completes even when Equibles is not running.
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
        mcp=None,                 # MCPClient | None — injected by pipeline
    ):
        self.alpha_vantage_key = alpha_vantage_key
        self.polygon_key       = polygon_key
        self.mcp               = mcp

    def fetch(self, ticker: str, depth: str = "full") -> dict:
        """
        Fetch all available data for a ticker.

        Returns a dict with keys:
          price_data          — Yahoo Finance price + fundamentals
          financials          — Alpha Vantage income statement + balance sheet
          earnings            — Polygon.io earnings calendar
          institutional       — Equibles 13F holders (depth=full + Equibles running)
          market_structure    — Equibles short interest + insider activity (depth=full + Equibles)
          technicals          — Equibles computed technical indicators (Equibles running)

        Missing sections are empty dicts / None — callers must handle gracefully.
        """
        ticker = ticker.upper().strip()
        result: dict = {
            "ticker":           ticker,
            "price_data":       {},
            "financials":       {},
            "earnings":         {},
            "institutional":    None,   # populated by Equibles when available
            "market_structure": None,   # populated by Equibles when available
            "technicals":       None,   # populated by Equibles when available
        }

        result["price_data"] = self._fetch_yahoo(ticker)

        if depth == "full":
            if self.alpha_vantage_key:
                result["financials"] = self._fetch_alpha_vantage(ticker)
            if self.polygon_key:
                result["earnings"] = self._fetch_polygon_earnings(ticker)

            # Equibles data (requires self-hosted Docker service)
            if self.mcp and self.mcp.is_available("equibles"):
                result["institutional"]    = self._fetch_equibles_institutional(ticker)
                result["market_structure"] = self._fetch_equibles_market_structure(ticker)
                result["technicals"]       = self._fetch_equibles_technicals(ticker)

        return result

    # ── Yahoo Finance ──────────────────────────────────────────────────────────

    def _fetch_yahoo(self, ticker: str) -> dict:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}

            return {
                "company_name":     info.get("longName", ticker),
                "sector":           info.get("sector", ""),
                "industry":         info.get("industry", ""),
                "current_price":    info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap":       info.get("marketCap"),
                "pe_ratio":         info.get("trailingPE"),
                "forward_pe":       info.get("forwardPE"),
                "eps":              info.get("trailingEps"),
                "revenue_growth":   info.get("revenueGrowth"),
                "profit_margin":    info.get("profitMargins"),
                "gross_margin":     info.get("grossMargins"),
                "debt_to_equity":   info.get("debtToEquity"),
                "free_cash_flow":   info.get("freeCashflow"),
                "52w_high":         info.get("fiftyTwoWeekHigh"),
                "52w_low":          info.get("fiftyTwoWeekLow"),
                "analyst_target":   info.get("targetMeanPrice"),
                "recommendation":   info.get("recommendationKey", ""),
                "short_ratio":      info.get("shortRatio"),
                "beta":             info.get("beta"),
                "dividend_yield":   info.get("dividendYield"),
                "business_summary": info.get("longBusinessSummary", "")[:500],
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
                    "symbol":   ticker,
                    "apikey":   self.alpha_vantage_key,
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
                    "symbol":   ticker,
                    "apikey":   self.alpha_vantage_key,
                })
                data2 = r2.json()
                annual2 = data2.get("annualReports", [])
                if annual2:
                    latest2 = annual2[0]
                    result["balance_sheet"] = {
                        "total_assets":      latest2.get("totalAssets"),
                        "total_liabilities": latest2.get("totalLiabilities"),
                        "total_equity":      latest2.get("totalShareholderEquity"),
                        "cash":              latest2.get("cashAndCashEquivalentsAtCarryingValue"),
                        "long_term_debt":    latest2.get("longTermDebt"),
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

    # ── Equibles ───────────────────────────────────────────────────────────────
    # All three methods fail silently — None is returned on any error so the
    # pipeline continues unaffected when Equibles is not running.

    def _fetch_equibles_institutional(self, ticker: str) -> dict | None:
        """
        Pull 13F institutional holder data from Equibles.
        Returns a dict ready to be passed to FundamentalsAnalystAgent.
        """
        raw = self.mcp.equibles_institutional_holders(ticker)
        if not raw:
            return None

        # Normalise the response — Equibles may use different key names across versions
        holders_raw = (
            raw.get("holders")
            or raw.get("institutionalHolders")
            or raw.get("data")
            or []
        )

        holders = []
        for h in holders_raw[:15]:    # top 15 is enough context for the LLM
            holders.append({
                "institution":           h.get("institution") or h.get("name") or h.get("institutionName", ""),
                "shares_held":           h.get("sharesHeld") or h.get("shares") or h.get("position"),
                "value_usd":             h.get("valueUsd") or h.get("value") or h.get("marketValue"),
                "pct_of_outstanding":    h.get("percentOfSharesOutstanding") or h.get("pctOutstanding"),
                "change_pct":            h.get("changePct") or h.get("changePercent") or h.get("quarterlyChange"),
                "change_direction":      h.get("changeDirection") or h.get("changeType"),
            })

        return {
            "total_institutional_pct": (
                raw.get("totalInstitutionalOwnershipPct")
                or raw.get("institutionalOwnershipPercent")
                or raw.get("totalPct")
            ),
            "holders":     holders,
            "quarter":     raw.get("quarter") or raw.get("asOfQuarter") or raw.get("reportingPeriod"),
            "summary":     raw.get("summary") or "",
        }

    def _fetch_equibles_market_structure(self, ticker: str) -> dict | None:
        """
        Pull FINRA short interest + SEC insider transactions + congressional trades.
        Returns a unified market structure dict.
        """
        short_raw   = self.mcp.equibles_short_interest(ticker)
        insider_raw = self.mcp.equibles_insider_transactions(ticker, days=90)
        congress_raw = self.mcp.equibles_congressional_trades(ticker, days=180)

        if not short_raw and not insider_raw and not congress_raw:
            return None

        result: dict = {}

        # Short interest
        if short_raw:
            result["short_volume_pct"]       = short_raw.get("shortVolumePct") or short_raw.get("shortVolume")
            result["short_interest_ratio"]   = short_raw.get("shortInterestRatio") or short_raw.get("daysToCover")
            result["fails_to_deliver"]       = short_raw.get("failsToDeliver") or short_raw.get("ftd")
            result["short_interest_trend"]   = short_raw.get("trend") or short_raw.get("shortTrend")

        # Insider transactions
        if insider_raw:
            result["insider_transactions"] = insider_raw[:10]   # cap at 10 for prompt budget

            # Derive net activity signal
            buys  = sum(1 for t in insider_raw if str(t.get("type", "")).lower() in ("buy", "purchase", "open market purchase"))
            sells = sum(1 for t in insider_raw if str(t.get("type", "")).lower() in ("sell", "sale", "open market sale"))
            if buys > sells:
                result["insider_net_activity"] = "net_buyer"
            elif sells > buys:
                result["insider_net_activity"] = "net_seller"
            else:
                result["insider_net_activity"] = "neutral"

        # Congressional trades
        if congress_raw:
            # Format as short human-readable strings
            congress_summaries = []
            for trade in congress_raw[:5]:
                member  = trade.get("member") or trade.get("name") or "Unknown"
                chamber = trade.get("chamber") or ""
                ttype   = trade.get("tradeType") or trade.get("type") or ""
                amount  = trade.get("amountRange") or trade.get("amount") or ""
                date    = trade.get("date") or trade.get("transactionDate") or ""
                congress_summaries.append(
                    f"{member} ({chamber}): {ttype} {amount} on {date}".strip(" :")
                )
            result["congressional_trades"] = congress_summaries

        return result if result else None

    def _fetch_equibles_technicals(self, ticker: str) -> dict | None:
        """
        Pull pre-computed technical indicators from Equibles daily price series.
        """
        raw = self.mcp.equibles_technical_indicators(ticker)
        if not raw:
            return None

        # Normalise key names across Equibles versions
        rsi    = raw.get("rsi14") or raw.get("rsi_14") or raw.get("rsi")
        sma50  = raw.get("sma50") or raw.get("sma_50") or raw.get("movingAverage50")
        sma200 = raw.get("sma200") or raw.get("sma_200") or raw.get("movingAverage200")
        price  = raw.get("currentPrice") or raw.get("lastPrice") or raw.get("close")

        # Derive position relative to moving averages
        def _vs(p, ma):
            if p is None or ma is None:
                return None
            if p > ma * 1.005:
                return "above"
            if p < ma * 0.995:
                return "below"
            return "at"

        trend_parts = []
        if rsi is not None:
            if rsi > 70:
                trend_parts.append(f"overbought (RSI {rsi:.1f})")
            elif rsi < 30:
                trend_parts.append(f"oversold (RSI {rsi:.1f})")
            else:
                trend_parts.append(f"neutral RSI {rsi:.1f}")
        if sma50 and price:
            trend_parts.append(f"{'above' if price > sma50 else 'below'} 50-day SMA")
        if sma200 and price:
            trend_parts.append(f"{'above' if price > sma200 else 'below'} 200-day SMA")

        return {
            "rsi_14":         rsi,
            "macd":           raw.get("macd") or raw.get("macdLine"),
            "macd_signal":    raw.get("macdSignal") or raw.get("signalLine"),
            "macd_histogram": raw.get("macdHistogram") or raw.get("histogram"),
            "bb_upper":       raw.get("bbUpper") or raw.get("bollingerUpper"),
            "bb_lower":       raw.get("bbLower") or raw.get("bollingerLower"),
            "sma_50":         sma50,
            "sma_200":        sma200,
            "volume_avg_30d": raw.get("volumeAvg30d") or raw.get("avgVolume30"),
            "price_vs_sma50":  _vs(price, sma50),
            "price_vs_sma200": _vs(price, sma200),
            "trend_signal":   "; ".join(trend_parts) if trend_parts else None,
        }
