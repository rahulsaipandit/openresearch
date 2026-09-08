"""
TrendAnalyst — five-year price history + annual financial trend data for a
ticker, plus a previous-year summary (requirement #7).

Pure yfinance data, no LLM call — the previous-year summary is computed
deterministically (simple % change arithmetic) rather than LLM-generated, so
change figures can't be hallucinated.
"""

import logging

import yfinance as yf

from agents.stock.volatility import (
    build_interpretation,
    daily_log_returns,
    ewma_volatility,
    garch_volatility,
)
from schemas.stock import TrendData, TrendPoint, VolatilityMetrics

logger = logging.getLogger(__name__)


class TrendAnalystAgent:
    def fetch(self, ticker: str) -> TrendData:
        ticker = ticker.upper().strip()
        price_history = self._fetch_price_history(ticker)
        annual = self._fetch_annual_financials(ticker)
        summary = self._build_previous_year_summary(price_history, annual)
        volatility = self._fetch_volatility(ticker)
        return TrendData(
            ticker=ticker,
            price_history=price_history,
            annual_financials=annual,
            previous_year_summary=summary,
            volatility=volatility,
        )

    def _fetch_price_history(self, ticker: str) -> list[TrendPoint]:
        try:
            hist = yf.Ticker(ticker).history(period="5y", interval="1mo")
            if hist.empty:
                return []
            points = []
            for idx, row in hist.iterrows():
                close = row.get("Close")
                if close is None or close != close:  # NaN check
                    continue
                points.append(TrendPoint(date=idx.strftime("%Y-%m-%d"), close=round(float(close), 2)))
            return points
        except Exception as e:
            logger.warning(f"TrendAnalyst price history failed for {ticker}: {e}")
            return []

    def _fetch_annual_financials(self, ticker: str) -> list[TrendPoint]:
        try:
            fin = yf.Ticker(ticker).financials  # annual income statement; columns = fiscal year-end dates
            if fin is None or fin.empty:
                return []
            points = []
            for col in sorted(fin.columns):
                revenue    = fin.loc["Total Revenue", col] if "Total Revenue" in fin.index else None
                net_income = fin.loc["Net Income", col] if "Net Income" in fin.index else None
                points.append(TrendPoint(
                    date=col.strftime("%Y-%m-%d"),
                    revenue=float(revenue) if revenue is not None and revenue == revenue else None,
                    net_income=float(net_income) if net_income is not None and net_income == net_income else None,
                ))
            return points
        except Exception as e:
            logger.warning(f"TrendAnalyst annual financials failed for {ticker}: {e}")
            return []

    def _fetch_volatility(self, ticker: str) -> VolatilityMetrics | None:
        """EWMA + GARCH(1,1) volatility off ~1y of daily closes (needs daily
        granularity, unlike the monthly 5y series used for the price chart)."""
        try:
            hist = yf.Ticker(ticker).history(period="1y", interval="1d")
            if hist.empty:
                return None
            closes = [float(c) for c in hist["Close"].tolist() if c == c]  # NaN check
        except Exception as e:
            logger.warning(f"TrendAnalyst daily history failed for {ticker}: {e}")
            return None

        returns = daily_log_returns(closes)
        ewma_pct = ewma_volatility(returns)
        ewma_pct = ewma_pct * 100 if ewma_pct is not None else None
        garch_forecast, garch_long_run = garch_volatility(returns)
        garch_forecast_pct = garch_forecast * 100 if garch_forecast is not None else None
        garch_long_run_pct = garch_long_run * 100 if garch_long_run is not None else None

        return VolatilityMetrics(
            ewma_annualized_pct=round(ewma_pct, 2) if ewma_pct is not None else None,
            garch_forecast_annualized_pct=round(garch_forecast_pct, 2) if garch_forecast_pct is not None else None,
            garch_long_run_annualized_pct=round(garch_long_run_pct, 2) if garch_long_run_pct is not None else None,
            interpretation=build_interpretation(ewma_pct, garch_forecast_pct, garch_long_run_pct),
        )

    def _build_previous_year_summary(
        self, price_history: list[TrendPoint], annual: list[TrendPoint]
    ) -> str:
        parts: list[str] = []

        if len(price_history) >= 13:
            start, end = price_history[-13].close, price_history[-1].close
            if start and end:
                pct = (end - start) / start * 100
                parts.append(f"Price {'up' if pct >= 0 else 'down'} {abs(pct):.1f}% over the past year.")

        if len(annual) >= 2:
            prev, latest = annual[-2], annual[-1]
            if prev.revenue and latest.revenue:
                pct = (latest.revenue - prev.revenue) / prev.revenue * 100
                parts.append(f"Revenue {'grew' if pct >= 0 else 'declined'} {abs(pct):.1f}% year-over-year.")

        return " ".join(parts) if parts else "Insufficient historical data for a previous-year comparison."
