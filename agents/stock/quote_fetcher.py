"""
QuoteFetcher — lightweight live price fetch for the watchlist tracker and
price-alert poller (docs/researchStockSolutions.md).

Deliberately separate from DataFetcherAgent.fetch(): that pulls a much
heavier profile (financials, Alpha Vantage, Polygon, Equibles) meant to
feed the LLM research pipeline for a single ticker on demand. This only
needs price + day change, and has to be cheap enough to call for every
watchlist ticker on a 5-minute cadence without hammering Yahoo Finance.

get_quotes_cached() is the entry point server.py actually uses: both the
alert poller and every open desktop client's GET /api/watchlist/quotes poll
would otherwise independently re-fetch the same tickers every ~5 minutes
with no shared cache — a short-TTL in-process cache keyed by ticker
collapses that to one real fetch per ticker per window regardless of how
many callers ask.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_MAX_PARALLEL_FETCHES = 8
_CACHE_TTL_SECONDS = 90  # well under the 5-minute poll cadence, just enough to dedupe overlapping callers

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}  # ticker -> (fetched_at, quote)


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
    any that fail. Always hits Yahoo Finance fresh — see get_quotes_cached()
    for the cached entry point used by server.py."""
    if not tickers:
        return []
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL_FETCHES, len(tickers))) as pool:
        results = pool.map(get_quote, tickers)
    return [quote for quote in results if quote is not None]


def get_quotes_cached(tickers: list[str], ttl_seconds: float = _CACHE_TTL_SECONDS) -> list[dict]:
    """Like get_quotes(), but reuses any quote fetched within the last
    `ttl_seconds` instead of re-fetching it — shared across every caller in
    the process (the alert poller and every desktop client's quotes poll),
    so overlapping tickers across callers cost one real fetch, not N."""
    tickers = [t.upper().strip() for t in tickers]
    if not tickers:
        return []

    now = time.monotonic()
    fresh: list[dict] = []
    stale_tickers: list[str] = []
    with _cache_lock:
        for ticker in tickers:
            cached = _cache.get(ticker)
            if cached is not None and now - cached[0] < ttl_seconds:
                fresh.append(cached[1])
            else:
                stale_tickers.append(ticker)

    if stale_tickers:
        refetched = get_quotes(stale_tickers)
        with _cache_lock:
            for quote in refetched:
                _cache[quote["ticker"]] = (now, quote)
        fresh.extend(refetched)

    return fresh
