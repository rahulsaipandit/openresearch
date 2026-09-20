"""
QuoteFetcher — lightweight, no-cache live price fetch for the watchlist
tracker and price-alert poller (docs/researchStockSolutions.md).

Deliberately separate from DataFetcherAgent.fetch(): that pulls a much
heavier profile (financials, Alpha Vantage, Polygon, Equibles) meant to
feed the LLM research pipeline for a single ticker on demand. This only
needs price + day change, and has to be cheap enough to call for every
watchlist ticker on a 5-minute cadence without hammering Yahoo Finance.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_MAX_PARALLEL_FETCHES = 8


def _fast_info_get(fast_info, *keys):
    """yfinance's FastInfo key casing has varied across versions
    (lastPrice vs last_price) — try each candidate key and return the
    first that resolves."""
    for key in keys:
        try:
            value = fast_info[key]
            if value is not None:
                return value
        except Exception:
            continue
    return None


def get_quote(ticker: str) -> dict | None:
    """Fetch current price + day change for a single ticker.
    Returns None on failure (network error, unknown ticker, etc.) so
    callers can skip it rather than fail the whole batch."""
    ticker = ticker.upper().strip()
    try:
        import yfinance as yf

        fast = yf.Ticker(ticker).fast_info
        price = _fast_info_get(fast, "lastPrice", "last_price")
        if price is None:
            return None

        prev_close = _fast_info_get(fast, "previousClose", "previous_close")
        # `is not None` (not truthiness) — a previousClose of exactly 0.0
        # (a newly-listed or halted ticker) is a legitimate value, not a
        # missing one, and `if prev_close` would wrongly treat it as absent.
        change = (price - prev_close) if prev_close is not None else None
        change_percent = (
            (change / prev_close * 100) if change is not None and prev_close else None
        )

        return {
            "ticker": ticker,
            "price": price,
            "change": change,
            "change_percent": change_percent,
            "currency": _fast_info_get(fast, "currency"),
        }
    except Exception as e:
        logger.warning(f"Quote fetch failed for {ticker}: {e}")
        return None


def get_quotes(tickers: list[str]) -> list[dict]:
    """Fetch quotes for multiple tickers in parallel (bounded pool — each
    get_quote() call is a blocking network request, so a plain sequential
    loop would serialize a 20-ticker watchlist into 20 round-trips), skipping
    any that fail."""
    if not tickers:
        return []
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL_FETCHES, len(tickers))) as pool:
        results = pool.map(get_quote, tickers)
    return [quote for quote in results if quote is not None]
