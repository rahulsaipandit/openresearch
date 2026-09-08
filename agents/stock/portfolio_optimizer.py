"""
PortfolioOptimizerAgent — single-period portfolio rebalancing.

Formulation follows Boyd, Busseti, Diamond et al., "Multi-Period Trading via
Convex Optimization" (the cvxportfolio paper): maximize expected return net
of a risk penalty, a 3/2-power market impact cost on trade size, and a
financing cost on short positions — solved as one convex program per call
(the single-period case of that paper; no multi-period trade scheduling).

Pure numeric agent, no LLM call — same philosophy as TrendAnalystAgent:
deterministic math over fetched price history, nothing for a model to
hallucinate.
"""

import logging
from datetime import datetime, timezone

import cvxpy as cp
import numpy as np
import yfinance as yf

from schemas.portfolio import (
    PortfolioHolding,
    PortfolioOptimizationResult,
    PortfolioOptimizeRequest,
    TradeRecommendation,
)

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
LOOKBACK_PERIOD = "2y"
_COV_RIDGE = 1e-6  # numerical floor so Sigma stays PSD for cvxpy


class PortfolioOptimizerAgent:
    def optimize(
        self,
        holdings: list[PortfolioHolding],
        request: PortfolioOptimizeRequest,
    ) -> PortfolioOptimizationResult:
        if not holdings:
            raise ValueError("Portfolio is empty — add holdings before optimizing.")

        tickers = [h.ticker for h in holdings]
        prices, returns = self._fetch_returns(tickers)

        # Drop any ticker whose price history failed to fetch, rather than
        # failing the whole optimization for one bad symbol.
        valid = [t for t in tickers if t in returns and len(returns[t]) >= 30]
        dropped = [t for t in tickers if t not in valid]
        if len(valid) < 2:
            raise ValueError("Need at least 2 tickers with sufficient price history to optimize.")

        current_prices = {t: prices[t] for t in valid}
        current_values = {h.ticker: h.shares * current_prices[h.ticker] for h in holdings if h.ticker in valid}
        total_value = sum(current_values.values())
        if total_value <= 0:
            raise ValueError("Portfolio has no positive market value to optimize against.")
        current_weights = np.array([current_values[t] / total_value for t in valid])

        mu, sigma = self._expected_return_and_cov(valid, returns)

        target_weights = self._solve(mu, sigma, current_weights, request)

        trades = []
        total_cost = 0.0
        for i, ticker in enumerate(valid):
            trade_w = float(target_weights[i] - current_weights[i])
            impact_cost = request.market_impact_coeff * abs(trade_w) ** 1.5
            holding_cost = request.short_borrow_rate * max(-target_weights[i], 0.0)
            total_cost += impact_cost + holding_cost
            trades.append(TradeRecommendation(
                ticker=ticker,
                current_weight=round(float(current_weights[i]), 4),
                target_weight=round(float(target_weights[i]), 4),
                trade_weight=round(trade_w, 4),
                action="buy" if trade_w > 0.005 else "sell" if trade_w < -0.005 else "hold",
                est_market_impact_cost=round(impact_cost, 6),
                est_holding_cost=round(holding_cost, 6),
            ))

        expected_return = float(mu @ target_weights)
        expected_vol = float(np.sqrt(target_weights @ sigma @ target_weights))

        notes = []
        if dropped:
            notes.append(f"Excluded from optimization (insufficient price history): {', '.join(dropped)}.")
        if not request.allow_short and any(t.target_weight < 0 for t in trades):
            notes.append("Unexpected negative target weight despite allow_short=False — check solver status.")

        return PortfolioOptimizationResult(
            as_of_date=datetime.now(timezone.utc).date().isoformat(),
            tickers=valid,
            expected_annual_return=round(expected_return, 4),
            expected_annual_volatility=round(expected_vol, 4),
            total_est_cost=round(total_cost, 6),
            trades=trades,
            notes=notes,
        )

    def _fetch_returns(self, tickers: list[str]) -> tuple[dict[str, float], dict[str, np.ndarray]]:
        """Returns (latest_close_by_ticker, daily_log_returns_by_ticker)."""
        prices: dict[str, float] = {}
        returns: dict[str, np.ndarray] = {}
        for ticker in tickers:
            try:
                hist = yf.Ticker(ticker).history(period=LOOKBACK_PERIOD, interval="1d")
                closes = hist["Close"].dropna()
                if closes.empty:
                    continue
                prices[ticker] = float(closes.iloc[-1])
                log_returns = np.diff(np.log(closes.to_numpy(dtype=float)))
                returns[ticker] = log_returns
            except Exception as e:
                logger.warning(f"PortfolioOptimizer price fetch failed for {ticker}: {e}")
        return prices, returns

    def _expected_return_and_cov(
        self, tickers: list[str], returns: dict[str, np.ndarray]
    ) -> tuple[np.ndarray, np.ndarray]:
        min_len = min(len(returns[t]) for t in tickers)
        matrix = np.column_stack([returns[t][-min_len:] for t in tickers])  # rows=days, cols=tickers
        mu = matrix.mean(axis=0) * TRADING_DAYS_PER_YEAR
        sigma = np.cov(matrix, rowvar=False) * TRADING_DAYS_PER_YEAR
        sigma = sigma + _COV_RIDGE * np.eye(len(tickers))
        return mu, sigma

    def _solve(
        self,
        mu: np.ndarray,
        sigma: np.ndarray,
        current_weights: np.ndarray,
        request: PortfolioOptimizeRequest,
    ) -> np.ndarray:
        n = len(mu)
        w = cp.Variable(n)
        trade = w - current_weights

        risk_term = request.risk_aversion * cp.quad_form(w, cp.psd_wrap(sigma))
        impact_term = request.market_impact_coeff * cp.sum(cp.power(cp.abs(trade), 1.5))
        short_term = request.short_borrow_rate * cp.sum(cp.pos(-w))

        objective = cp.Maximize(mu @ w - risk_term - impact_term - short_term)

        constraints = [cp.sum(w) == 1]
        if request.allow_short:
            constraints += [w >= -request.max_position_weight, w <= request.max_position_weight]
        else:
            constraints += [w >= 0, w <= request.max_position_weight]

        problem = cp.Problem(objective, constraints)
        problem.solve(solver=cp.ECOS)

        if w.value is None:
            raise ValueError(f"Portfolio optimization did not converge (status: {problem.status}).")
        return w.value
