"""
Pydantic schemas for Portfolio Management.

Holdings persist like the watchlist (schemas/watchlist.py). The optimizer
schemas follow the single-period formulation in Boyd et al., "Multi-Period
Trading via Convex Optimization" / cvxportfolio: expected return net of a
3/2-power market impact cost and a financing cost on short positions,
maximized subject to risk aversion — see agents/stock/portfolio_optimizer.py.
"""

from typing import Optional
from pydantic import BaseModel


class PortfolioHolding(BaseModel):
    ticker: str
    shares: float
    cost_basis: Optional[float] = None
    added_at: str


class PortfolioOptimizeRequest(BaseModel):
    risk_aversion: float = 5.0          # higher = more risk-averse (weight on variance)
    market_impact_coeff: float = 0.01   # cost_i = coeff * |trade_weight_i|^1.5
    short_borrow_rate: float = 0.02     # annualized financing cost on short weights
    max_position_weight: float = 0.4    # per-ticker |weight| cap
    allow_short: bool = False


class TradeRecommendation(BaseModel):
    ticker: str
    current_weight: float
    target_weight: float
    trade_weight: float          # target - current; positive = buy, negative = sell
    action: str                  # "buy" | "sell" | "hold"
    est_market_impact_cost: float
    est_holding_cost: float


class FactorExposure(BaseModel):
    """
    PCA + Random Matrix Theory diversification check — see
    agents/stock/factor_decomposition.py and
    docs/Stocks/designStock_FactorDecompositionRMT.md.
    """
    n_tickers: int
    n_observations: int
    mp_noise_threshold: float             # Marchenko-Pastur upper edge; eigenvalues above this are real factors
    n_significant_factors: int            # eigenvalues clearing the MP threshold
    variance_explained_by_factor: list[float]  # top eigenvalues' share of total variance, descending
    top_factor_variance_share: float      # variance_explained_by_factor[0]
    concentration_warning: bool           # True when the top factor dominates (portfolio is one bet in a costume)


class PortfolioOptimizationResult(BaseModel):
    as_of_date: str
    tickers: list[str]
    expected_annual_return: float
    expected_annual_volatility: float
    total_est_cost: float
    trades: list[TradeRecommendation]
    notes: list[str]
    factor_exposure: Optional[FactorExposure] = None
