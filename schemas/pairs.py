"""
Pydantic schemas for Kalman-filter pairs trading analysis.

See agents/stock/pairs_trading.py for the model and
docs/Stocks/designStock_KalmanPairsTrading.md for the design rationale
(a corrected implementation of the "Kalman Filters for Adaptive Pairs
Trading" article — the original's spread/z-score/half-life/sizing math had
several bugs; this schema reflects the corrected version).
"""

from typing import Optional
from pydantic import BaseModel


class PairsAnalysisRequest(BaseModel):
    ticker_y: str
    ticker_x: str
    lookback: str = "2y"          # yfinance period string
    capital: float = 100_000.0    # for share-quantity sizing
    entry_z: float = 2.0          # |z| at/above this triggers a signal


class KalmanHistoryPoint(BaseModel):
    date: str
    hedge_ratio: float
    spread: float
    z_score: float


class PairsAnalysisResult(BaseModel):
    as_of_date: str
    ticker_y: str
    ticker_x: str
    n_observations: int

    engle_granger_pvalue: float   # cointegration test over the full lookback window
    cointegrated: bool

    adf_pvalue: float             # stationarity of the most recent spread window
    stationary_now: bool

    half_life_days: Optional[float]  # None when the spread isn't mean-reverting

    hedge_ratio: float             # latest Kalman-filtered beta_t
    intercept: float                # latest Kalman-filtered alpha_t
    spread: float                   # latest Y_t - (alpha_t + beta_t * X_t)
    z_score: float                  # innovation / sqrt(innovation variance), from the filter itself
    observation_noise: float        # adaptively estimated R_t

    signal: str                     # "long_spread" | "short_spread" | "flat"
    shares_y: float
    shares_x: float

    warnings: list[str]
    history: list[KalmanHistoryPoint]  # recent tail, for charting
