"""
PairsTradingAgent — Kalman-filtered adaptive hedge ratio for pairs trading.

This is a corrected implementation of the model described in "How To Use
Kalman Filters To Build Adaptive Pairs Trading Strategies": model the spread
between two cointegrated assets as Y_t = alpha_t + beta_t * X_t + eps_t,
treating (alpha_t, beta_t) as a hidden state that follows a random walk
(state-space model) instead of a fixed-window OLS regression. See
docs/Stocks/designStock_KalmanPairsTrading.md for what was wrong with the
reference implementation and why each fix below was made:

  - Z-scores use the Kalman filter's own innovation variance (P_t|t-1 folded
    through the observation model), not a rolling historical std — the
    filter already knows its own uncertainty at every step.
  - The observation noise R is adaptively estimated online (innovation-based
    adaptive estimation / Mehra 1970) rather than fixed, so the filter
    doesn't over-react in calm markets or under-react in volatile ones. This
    is a cheaper substitute for a full EM re-fit, appropriate for a filter
    that gets recomputed on demand or every few minutes rather than trained
    once offline.
  - Cointegration is re-checked every call (Engle-Granger over the full
    lookback window, plus an Augmented Dickey-Fuller test on just the recent
    spread) instead of assumed permanent from a one-time test — a pair that
    stops being cointegrated turns a mean-reversion filter into an
    accidental trend-follower that keeps chasing beta.
  - Half-life comes from the same Kalman-filtered spread series used for
    trading, and gates the signal (no signal outside the 1-20 day window or
    when the AR coefficient implies no mean reversion) instead of being
    reported without being used.
  - Position sizing uses share quantities (Q_y = capital / price_y,
    Q_x = beta * Q_y), not raw percent-change subtraction, which isn't valid
    for a dollar-neutral hedge.

Pure numeric agent, no LLM call — same philosophy as PortfolioOptimizerAgent
and FactorDecompositionAgent. Stateless: each call re-fetches history and
re-runs the filter from scratch, since it's designed to be called on demand
or on a short polling interval rather than run as a persistent process.
"""

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.stattools import adfuller, coint

from schemas.pairs import KalmanHistoryPoint, PairsAnalysisRequest, PairsAnalysisResult

logger = logging.getLogger(__name__)

MIN_OBSERVATIONS = 60
STATIONARITY_WINDOW = 60          # trailing window for the "is it still cointegrated" ADF check
HISTORY_TAIL = 60                 # points returned for charting
SIGNIFICANCE = 0.05
HALF_LIFE_MIN_DAYS = 1.0
HALF_LIFE_MAX_DAYS = 20.0

# Random-walk transition noise for (alpha, beta): small relative to typical
# state scale, so the hedge ratio adapts gradually rather than jumping on
# every tick. A fixed delta is standard practice for this filter (see e.g.
# Ernest Chan's pairs-trading writeups); it does not need per-pair tuning
# the way R does, because R is dominated by market noise while Q reflects a
# modeling choice about how fast a "true" hedge ratio can drift.
_DELTA = 1e-4
_TRANSITION_COV = _DELTA / (1 - _DELTA) * np.eye(2)
_R_FORGETTING = 0.98               # EWMA weight for adaptive observation-noise estimation
_R_MIN = 1e-6


class PairsTradingAgent:
    def analyze(self, request: PairsAnalysisRequest) -> PairsAnalysisResult:
        y_prices, x_prices = self._fetch_aligned_prices(request.ticker_y, request.ticker_x, request.lookback)
        if len(y_prices) < MIN_OBSERVATIONS:
            raise ValueError(
                f"Need at least {MIN_OBSERVATIONS} aligned trading days for {request.ticker_y}/{request.ticker_x}, "
                f"got {len(y_prices)}."
            )

        y = y_prices.to_numpy(dtype=float)
        x = x_prices.to_numpy(dtype=float)
        dates = y_prices.index

        eg_pvalue = float(coint(y, x)[1])
        cointegrated = eg_pvalue < SIGNIFICANCE

        betas, alphas, spreads, z_scores, final_r = self._run_kalman(y, x)

        adf_window = spreads[-STATIONARITY_WINDOW:]
        adf_pvalue = float(adfuller(adf_window, result_object=False)[1])
        stationary_now = adf_pvalue < SIGNIFICANCE

        half_life = self._half_life(spreads)

        warnings: list[str] = []
        tradable = True
        if not cointegrated:
            warnings.append(
                f"Pair fails the Engle-Granger cointegration test (p={eg_pvalue:.3f}) — "
                "the long-run relationship may not be stable enough to trade."
            )
            tradable = False
        if not stationary_now:
            warnings.append(
                f"Recent spread fails an ADF stationarity test (p={adf_pvalue:.3f}) — cointegration may have "
                "broken down; the filter could be chasing a trend rather than tracking mean reversion."
            )
            tradable = False
        if half_life is None:
            warnings.append("Spread shows no mean reversion (non-negative AR coefficient) — half-life is undefined.")
            tradable = False
        elif not (HALF_LIFE_MIN_DAYS <= half_life <= HALF_LIFE_MAX_DAYS):
            warnings.append(
                f"Half-life of {half_life:.1f} days is outside the recommended "
                f"{HALF_LIFE_MIN_DAYS:.0f}-{HALF_LIFE_MAX_DAYS:.0f} day trading window."
            )
            tradable = False

        latest_z = float(z_scores[-1])
        if tradable and latest_z >= request.entry_z:
            signal = "short_spread"   # spread too high: short Y, long beta*X
        elif tradable and latest_z <= -request.entry_z:
            signal = "long_spread"    # spread too low: long Y, short beta*X
        else:
            signal = "flat"

        shares_y, shares_x = self._position_sizes(signal, request.capital, float(y[-1]), float(betas[-1]))

        history = [
            KalmanHistoryPoint(
                date=pd.Timestamp(d).date().isoformat(),
                hedge_ratio=round(float(b), 6),
                spread=round(float(s), 6),
                z_score=round(float(z), 4),
            )
            for d, b, s, z in zip(dates[-HISTORY_TAIL:], betas[-HISTORY_TAIL:], spreads[-HISTORY_TAIL:], z_scores[-HISTORY_TAIL:])
        ]

        return PairsAnalysisResult(
            as_of_date=datetime.now(timezone.utc).date().isoformat(),
            ticker_y=request.ticker_y,
            ticker_x=request.ticker_x,
            n_observations=len(y),
            engle_granger_pvalue=round(eg_pvalue, 4),
            cointegrated=cointegrated,
            adf_pvalue=round(adf_pvalue, 4),
            stationary_now=stationary_now,
            half_life_days=round(half_life, 2) if half_life is not None else None,
            hedge_ratio=round(float(betas[-1]), 6),
            intercept=round(float(alphas[-1]), 6),
            spread=round(float(spreads[-1]), 6),
            z_score=round(latest_z, 4),
            observation_noise=round(float(final_r), 6),
            signal=signal,
            shares_y=round(shares_y, 4),
            shares_x=round(shares_x, 4),
            warnings=warnings,
            history=history,
        )

    def _fetch_aligned_prices(self, ticker_y: str, ticker_x: str, lookback: str) -> tuple[pd.Series, pd.Series]:
        y_hist = yf.Ticker(ticker_y).history(period=lookback, interval="1d")["Close"].dropna()
        x_hist = yf.Ticker(ticker_x).history(period=lookback, interval="1d")["Close"].dropna()
        y_hist.index = y_hist.index.tz_localize(None) if y_hist.index.tz is not None else y_hist.index
        x_hist.index = x_hist.index.tz_localize(None) if x_hist.index.tz is not None else x_hist.index
        aligned = pd.concat({"y": y_hist, "x": x_hist}, axis=1, join="inner").dropna()
        return aligned["y"], aligned["x"]

    def _run_kalman(self, y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
        """
        Two-state Kalman filter, state = [alpha, beta], observation
        y_t = [1, x_t] @ state + noise. Returns per-step (beta, alpha,
        spread, z_score) arrays plus the final adaptive R estimate.
        """
        n = len(y)
        init_window = min(30, n // 2)
        init_beta, init_alpha = np.polyfit(x[:init_window], y[:init_window], 1)
        init_resid = y[:init_window] - (init_alpha + init_beta * x[:init_window])
        r = max(float(np.var(init_resid)), _R_MIN)

        state = np.array([init_alpha, init_beta])
        cov = np.eye(2) * 1.0

        betas = np.empty(n)
        alphas = np.empty(n)
        spreads = np.empty(n)
        z_scores = np.empty(n)

        for t in range(n):
            # Predict (random-walk transition: identity + process noise)
            cov_pred = cov + _TRANSITION_COV

            h = np.array([1.0, x[t]])
            y_pred = h @ state
            innovation = y[t] - y_pred
            innovation_var = float(h @ cov_pred @ h + r)

            gain = cov_pred @ h / innovation_var
            state = state + gain * innovation
            cov = cov_pred - np.outer(gain, h) @ cov_pred

            # Innovation-based adaptive observation noise (Mehra 1970): track
            # how much of the innovation variance isn't explained by state
            # uncertainty, and fold that into R with exponential forgetting.
            residual_var = max(innovation ** 2 - float(h @ cov_pred @ h), _R_MIN)
            r = _R_FORGETTING * r + (1 - _R_FORGETTING) * residual_var

            alphas[t] = state[0]
            betas[t] = state[1]
            spreads[t] = innovation  # spread computed against the pre-update (a priori) state
            z_scores[t] = innovation / np.sqrt(innovation_var)

        return betas, alphas, spreads, z_scores, r

    def _half_life(self, spread: np.ndarray) -> float | None:
        """
        Half-life of mean reversion from the discretized OU process:
        delta_s_t = a + rho * s_{t-1} + eps. rho >= 0 means no mean
        reversion (half-life undefined); otherwise
        half_life = -ln(2) / ln(1 + rho).
        """
        s_lag = spread[:-1]
        delta_s = spread[1:] - s_lag
        design = np.column_stack([np.ones_like(s_lag), s_lag])
        coeffs, *_ = np.linalg.lstsq(design, delta_s, rcond=None)
        rho = coeffs[1]
        if rho >= 0:
            return None
        return float(-np.log(2) / np.log(1 + rho))

    def _position_sizes(self, signal: str, capital: float, price_y: float, beta: float) -> tuple[float, float]:
        if signal == "flat" or price_y <= 0:
            return 0.0, 0.0
        q_y = capital / price_y
        q_x = beta * q_y
        if signal == "long_spread":
            return q_y, -q_x
        return -q_y, q_x  # short_spread
