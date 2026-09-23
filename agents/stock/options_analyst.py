"""
OptionsAnalyst — puts/calls volume, open-interest, and IV-skew snapshot.

Same philosophy as SignalAgent/BacktestEngine (see
docs/designStock_DashboardUI.md and docs/designStock_TechnicalSignalsAndBacktesting.md):
pure deterministic math over yfinance's option chain, no LLM call, nothing to
hallucinate. The put/call ratio, open-interest concentration, and IV skew
computed here are handed to the LLM only as pre-computed facts to narrate
(see ResearchSynthesizerAgent), never as something it derives itself.

"Unusual" call/put activity is flagged relative to the ticker's own trailing
30-day put/call ratio (persisted in OptionsHistoryStore), not an absolute
threshold — a ratio of 0.8 means something different for a stock that
normally sits at 0.4 vs. one that normally sits at 1.2.
"""

import logging
import math
from datetime import date

import yfinance as yf

from schemas.stock import OptionsData
from store.options_history_store import OptionsHistoryStore

logger = logging.getLogger(__name__)

NUM_EXPIRIES = 3               # nearest expiries to aggregate across
NEAR_MONEY_BAND = 0.05         # strikes within 5% of spot count toward the IV-skew read
UNUSUAL_RATIO_MULTIPLE = 1.5   # today's ratio vs. 30d avg beyond this multiple is "unusual"


def _safe_int(v) -> int:
    """yfinance option-chain rows use NaN (not None) for missing volume/OI."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0
    return int(v)


class OptionsAnalyst:
    def __init__(self, store: OptionsHistoryStore | None = None):
        self.store = store or OptionsHistoryStore()

    def analyze(self, ticker: str) -> OptionsData | None:
        """
        Compute a puts/calls snapshot for a ticker. Returns None if the
        ticker has no listed options or the chain can't be fetched.
        """
        ticker = ticker.upper().strip()
        try:
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                return None
            spot = t.info.get("currentPrice") or t.info.get("regularMarketPrice")
        except Exception as e:
            logger.warning(f"OptionsAnalyst failed to load option chain for {ticker}: {e}")
            return None

        call_volume = 0
        put_volume = 0
        call_oi_by_strike: dict[float, int] = {}
        put_oi_by_strike: dict[float, int] = {}
        call_iv_near: list[float] = []
        put_iv_near: list[float] = []

        for expiry in expiries[:NUM_EXPIRIES]:
            try:
                chain = t.option_chain(expiry)
            except Exception as e:
                logger.debug(f"OptionsAnalyst chain fetch failed for {ticker} {expiry}: {e}")
                continue

            call_volume += self._aggregate_side(chain.calls, spot, call_oi_by_strike, call_iv_near)
            put_volume += self._aggregate_side(chain.puts, spot, put_oi_by_strike, put_iv_near)

        if call_volume == 0 and put_volume == 0:
            return None

        ratio = (put_volume / call_volume) if call_volume else None

        self.store.record(ticker, date.today().isoformat(), ratio)
        avg_30d = self.store.trailing_average(ticker, days=30, exclude_today=True)

        unusual_call = False
        unusual_put = False
        if ratio is not None and avg_30d:
            if ratio <= avg_30d / UNUSUAL_RATIO_MULTIPLE:
                unusual_call = True   # ratio much lower than normal -> call-heavy
            elif ratio >= avg_30d * UNUSUAL_RATIO_MULTIPLE:
                unusual_put = True    # ratio much higher than normal -> put-heavy

        dominant_call_strike = max(call_oi_by_strike, key=call_oi_by_strike.get) if call_oi_by_strike else None
        dominant_put_strike = max(put_oi_by_strike, key=put_oi_by_strike.get) if put_oi_by_strike else None

        iv_skew = None
        if call_iv_near and put_iv_near:
            iv_skew = (sum(put_iv_near) / len(put_iv_near)) - (sum(call_iv_near) / len(call_iv_near))

        data = OptionsData(
            put_call_volume_ratio=round(ratio, 3) if ratio is not None else None,
            put_call_ratio_30d_avg=round(avg_30d, 3) if avg_30d is not None else None,
            unusual_call_activity=unusual_call,
            unusual_put_activity=unusual_put,
            iv_skew=round(iv_skew, 4) if iv_skew is not None else None,
            dominant_call_strike=dominant_call_strike,
            dominant_put_strike=dominant_put_strike,
            nearest_expiry=expiries[0],
            total_call_volume=call_volume,
            total_put_volume=put_volume,
            summary="",  # filled in immediately below, once all fields above are known
        )
        data.summary = self._summarize(data, spot)
        return data

    def _aggregate_side(
        self,
        rows,
        spot: float | None,
        oi_by_strike: dict[float, int],
        iv_near: list[float],
    ) -> int:
        """Aggregates one side (calls or puts) of an option chain — volume,
        open-interest-by-strike, and near-the-money implied vol. Shared by
        both calls-processing and puts-processing in analyze() so a future
        field addition (e.g. gamma) only needs to be made once."""
        volume = 0
        for _, row in rows.iterrows():
            strike = float(row["strike"])
            volume += _safe_int(row.get("volume"))
            oi_by_strike[strike] = oi_by_strike.get(strike, 0) + _safe_int(row.get("openInterest"))
            iv = row.get("impliedVolatility")
            if spot and iv and not math.isnan(iv) and abs(strike - spot) / spot < NEAR_MONEY_BAND:
                iv_near.append(float(iv))
        return volume

    def _pct_vs_spot(self, strike: float, spot: float | None) -> str:
        if not spot:
            return ""
        return f" ({(strike / spot - 1) * 100:+.0f}% vs spot)"

    def _summarize(self, data: OptionsData, spot: float | None) -> str:
        parts = []
        if data.put_call_volume_ratio is not None:
            vs_avg = f" vs {data.put_call_ratio_30d_avg:.2f} 30-day avg" if data.put_call_ratio_30d_avg is not None else ""
            parts.append(f"put/call volume ratio {data.put_call_volume_ratio:.2f}{vs_avg}")
        if data.unusual_call_activity:
            parts.append("call volume running well above its recent average")
        if data.unusual_put_activity:
            parts.append("put volume running well above its recent average")
        if data.dominant_call_strike is not None:
            parts.append(f"heaviest call open interest at ${data.dominant_call_strike:.0f}{self._pct_vs_spot(data.dominant_call_strike, spot)}")
        if data.dominant_put_strike is not None:
            parts.append(f"heaviest put open interest at ${data.dominant_put_strike:.0f}{self._pct_vs_spot(data.dominant_put_strike, spot)}")
        if data.iv_skew is not None:
            leaning = "put" if data.iv_skew > 0 else "call"
            parts.append(f"{leaning} implied vol running higher near the money")
        return "; ".join(parts)
