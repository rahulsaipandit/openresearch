import numpy as np
import pytest

from agents.stock.volatility import (
    build_interpretation,
    daily_log_returns,
    ewma_volatility,
    garch_volatility,
)


def test_daily_log_returns_basic():
    closes = [100.0, 101.0, 99.0, 102.0]
    returns = daily_log_returns(closes)
    assert len(returns) == 3
    assert returns[0] == pytest.approx(np.log(101.0 / 100.0))


def test_daily_log_returns_drops_non_positive_and_short_series():
    assert daily_log_returns([100.0]).size == 0
    assert daily_log_returns([]).size == 0
    returns = daily_log_returns([100.0, -5.0, 0.0, 110.0])
    assert len(returns) == 1  # only the 100 -> 110 transition survives


def test_ewma_volatility_higher_for_more_volatile_series():
    rng = np.random.default_rng(42)
    calm = rng.normal(0, 0.005, 300)
    turbulent = rng.normal(0, 0.03, 300)
    calm_vol = ewma_volatility(calm)
    turbulent_vol = ewma_volatility(turbulent)
    assert calm_vol is not None and turbulent_vol is not None
    assert turbulent_vol > calm_vol


def test_ewma_volatility_none_for_too_short_series():
    assert ewma_volatility(np.array([0.01])) is None
    assert ewma_volatility(np.array([])) is None


def test_garch_volatility_none_below_min_length():
    forecast, long_run = garch_volatility(np.random.default_rng(0).normal(0, 0.01, 10))
    assert forecast is None and long_run is None


def test_garch_volatility_fits_on_sufficient_history():
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.015, 300)
    forecast, long_run = garch_volatility(returns)
    assert forecast is not None
    assert long_run is not None
    assert forecast > 0
    assert long_run > 0


def test_build_interpretation_reports_insufficient_data():
    msg = build_interpretation(None, None, None)
    assert "Insufficient" in msg


def test_build_interpretation_flags_elevated_volatility():
    msg = build_interpretation(30.0, 40.0, 20.0)
    assert "more turbulent than typical" in msg


def test_build_interpretation_flags_calm_volatility():
    msg = build_interpretation(10.0, 10.0, 20.0)
    assert "calmer than typical" in msg
