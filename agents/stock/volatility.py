"""
Volatility analytics — EWMA (RiskMetrics-style) and GARCH(1,1) daily-return
volatility estimators.

Pure numeric functions, no LLM call and no network I/O — TrendAnalystAgent
feeds these a daily close-price series it has already fetched. Kept separate
from trend_analyst.py so the math is independently unit-testable against
synthetic return series.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
EWMA_DECAY = 0.94  # RiskMetrics standard daily decay factor
MIN_RETURNS_FOR_GARCH = 30  # below this, a GARCH(1,1) fit is unreliable


def daily_log_returns(closes: list[float]) -> np.ndarray:
    """Log returns from a chronological close-price series, dropping non-positive prices."""
    prices = np.array([c for c in closes if c is not None and c > 0], dtype=float)
    if len(prices) < 2:
        return np.array([])
    return np.diff(np.log(prices))


def ewma_volatility(returns: np.ndarray, decay: float = EWMA_DECAY) -> float | None:
    """
    Annualized EWMA volatility (RiskMetrics lambda=0.94): the variance
    recursion var_t = decay * var_{t-1} + (1 - decay) * return_{t-1}^2 gives
    recent returns more weight than older ones via smooth exponential decay.
    Seeded with the full-sample variance so short histories still produce a
    stable estimate rather than starting from zero.
    """
    if len(returns) < 2:
        return None
    var = float(np.var(returns))
    for r in returns:
        var = decay * var + (1 - decay) * r**2
    return float(np.sqrt(var * TRADING_DAYS_PER_YEAR))


def garch_volatility(returns: np.ndarray) -> tuple[float | None, float | None]:
    """
    GARCH(1,1) one-day-ahead forecast + long-run (unconditional) annualized
    volatility, via the `arch` package. GARCH extends EWMA by adding a
    long-run average variance (omega) that current volatility mean-reverts
    toward, rather than decaying purely off recent shocks.

    Returns (forecast_vol_annualized, long_run_vol_annualized) as fractions
    (e.g. 0.32 for 32%); (None, None) if history is too short or the fit fails.
    """
    if len(returns) < MIN_RETURNS_FOR_GARCH:
        return None, None
    try:
        from arch import arch_model

        # arch_model recommends returns scaled to roughly O(1)-O(10) (percent
        # points) for numerical stability of the optimizer.
        model = arch_model(returns * 100, mean="Zero", vol="Garch", p=1, q=1, dist="normal")
        res = model.fit(disp="off")

        forecast = res.forecast(horizon=1, reindex=False)
        next_day_var_pct2 = float(forecast.variance.values[-1, 0])
        forecast_vol = np.sqrt(next_day_var_pct2 * TRADING_DAYS_PER_YEAR) / 100

        omega, alpha, beta = res.params["omega"], res.params["alpha[1]"], res.params["beta[1]"]
        persistence = alpha + beta
        long_run_var_pct2 = omega / (1 - persistence) if persistence < 1 else next_day_var_pct2
        long_run_vol = np.sqrt(long_run_var_pct2 * TRADING_DAYS_PER_YEAR) / 100

        return float(forecast_vol), float(long_run_vol)
    except Exception as e:
        logger.warning(f"GARCH(1,1) fit failed: {e}")
        return None, None


def build_interpretation(ewma_pct: float | None, garch_forecast_pct: float | None, garch_long_run_pct: float | None) -> str:
    """Deterministic plain-English summary so no LLM invents the comparison."""
    if ewma_pct is None:
        return "Insufficient daily price history to estimate volatility."

    parts = [f"Recent (EWMA) annualized volatility is {ewma_pct:.1f}%."]
    if garch_forecast_pct is not None and garch_long_run_pct is not None:
        if garch_forecast_pct > garch_long_run_pct * 1.1:
            parts.append(
                f"GARCH forecasts {garch_forecast_pct:.1f}% next-day volatility, above its "
                f"{garch_long_run_pct:.1f}% long-run average — currently more turbulent than typical."
            )
        elif garch_forecast_pct < garch_long_run_pct * 0.9:
            parts.append(
                f"GARCH forecasts {garch_forecast_pct:.1f}% next-day volatility, below its "
                f"{garch_long_run_pct:.1f}% long-run average — currently calmer than typical."
            )
        else:
            parts.append(
                f"GARCH forecasts {garch_forecast_pct:.1f}% next-day volatility, close to its "
                f"{garch_long_run_pct:.1f}% long-run average."
            )
    return " ".join(parts)
