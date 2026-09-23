"""Pydantic schemas for the Stock Research pipeline."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class ValuationSummary(BaseModel):
    fair_value_low: float
    fair_value_high: float
    current_price: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    eps: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    profit_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    market_cap: Optional[float] = None
    moat_assessment: str = ""
    key_metrics: dict[str, str] = Field(default_factory=dict)
    # Deterministic passthrough facts set directly from fetched price data
    # (never from the LLM response) — see FundamentalsAnalystAgent.analyze().
    fifty_two_week_low: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    dividend_yield: Optional[float] = None
    volume: Optional[int] = None
    shares_outstanding: Optional[int] = None


class SentimentSummary(BaseModel):
    tone: Literal["bullish", "neutral", "bearish"]
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    analyst_consensus: Optional[str] = None
    recent_headlines: list[str] = Field(default_factory=list)
    sec_filings_summary: Optional[str] = None


class InstitutionalHolder(BaseModel):
    """A single institutional 13F filer and their reported position."""
    institution: str                          # e.g. "Vanguard Group Inc"
    shares_held: Optional[int] = None         # shares as of last 13F
    value_usd: Optional[float] = None         # market value in USD
    pct_of_shares_outstanding: Optional[float] = None
    change_pct: Optional[float] = None        # QoQ change in position (+ = added, - = reduced)
    change_direction: Optional[Literal["increased", "decreased", "new", "unchanged"]] = None


class InstitutionalSnapshot(BaseModel):
    """
    Aggregated 13F institutional ownership data from Equibles.
    Present only when Equibles is running and depth="full".
    """
    total_institutional_ownership_pct: Optional[float] = None  # % of float held by institutions
    top_holders: list[InstitutionalHolder] = Field(default_factory=list)
    recent_changes_summary: str = ""          # plain-English summary of notable QoQ moves
    as_of_quarter: Optional[str] = None       # e.g. "2026-Q1"


class InsiderTransaction(BaseModel):
    """A single SEC Form 3 or Form 4 insider transaction."""
    insider_name: str
    title: Optional[str] = None               # e.g. "CEO", "Director"
    transaction_type: Optional[str] = None    # "Buy", "Sell", "Exercise"
    shares: Optional[int] = None
    price_per_share: Optional[float] = None
    total_value: Optional[float] = None
    transaction_date: Optional[str] = None
    form_type: Optional[str] = None           # "3", "4"


class MarketStructureData(BaseModel):
    """
    Short interest, insider activity, and alternative market structure signals.
    Sourced from FINRA (short volume), SEC (fails-to-deliver), and SEC Form 3/4.
    Present only when Equibles is running and depth="full".
    """
    # Short interest (FINRA)
    short_volume_pct: Optional[float] = None          # short volume as % of daily total
    short_interest_ratio: Optional[float] = None      # days-to-cover
    fails_to_deliver: Optional[int] = None            # SEC fail-to-deliver count (last reported)
    short_interest_trend: Optional[str] = None        # "rising", "falling", "stable"

    # Insider activity (SEC Form 3/4)
    recent_insider_transactions: list[InsiderTransaction] = Field(default_factory=list)
    insider_net_activity: Optional[Literal["net_buyer", "net_seller", "neutral"]] = None
    insider_summary: str = ""                          # e.g. "CEO sold $4M (3 transactions, 90 days)"

    # Congressional disclosures
    congressional_trades: list[str] = Field(default_factory=list)   # human-readable summaries


class TechnicalIndicators(BaseModel):
    """
    Computed technical indicators from Equibles daily price series.
    Present only when Equibles is running.
    """
    rsi_14: Optional[float] = None            # 14-day RSI (>70 overbought, <30 oversold)
    macd: Optional[float] = None              # MACD line
    macd_signal: Optional[float] = None       # Signal line
    macd_histogram: Optional[float] = None
    bb_upper: Optional[float] = None          # Bollinger Band upper
    bb_lower: Optional[float] = None          # Bollinger Band lower
    sma_50: Optional[float] = None            # 50-day simple moving average
    sma_200: Optional[float] = None           # 200-day simple moving average
    volume_avg_30d: Optional[float] = None    # 30-day average daily volume
    price_vs_sma50: Optional[str] = None      # "above", "below", "at"
    price_vs_sma200: Optional[str] = None     # "above", "below", "at"
    trend_signal: Optional[str] = None        # brief technical summary


class CandlestickPattern(BaseModel):
    """A single detected candlestick pattern, computed deterministically from OHLC bars."""
    pattern: str                              # e.g. "bullish_engulfing", "hammer", "doji"
    date: str                                 # ISO date of the bar the pattern completed on
    direction: Literal["bullish", "bearish", "neutral"]


class SignalTrigger(BaseModel):
    """A single buy/sell trigger produced by the rule-based signal agent."""
    date: str
    action: Literal["buy", "sell"]
    reason: str                               # e.g. "RSI oversold (24.3) + bullish engulfing"


class SignalSet(BaseModel):
    """
    Deterministic technical signals — candlestick patterns + indicator-based
    buy/sell triggers. No LLM involved in computing any of this; see
    agents/stock/signal_agent.py for why.
    """
    patterns: list[CandlestickPattern] = Field(default_factory=list)
    triggers: list[SignalTrigger] = Field(default_factory=list)
    current_signal: Literal["buy", "sell", "hold"] = "hold"
    summary: str = ""                         # deterministic plain-English rollup


class BacktestResult(BaseModel):
    """
    Backtest of the SignalSet's buy/sell triggers against historical prices,
    with a sealed out-of-sample window so the reported edge isn't just
    curve-fit to the full lookback period. See agents/stock/backtest_engine.py.
    """
    strategy_return_pct: Optional[float] = None
    strategy_sharpe: Optional[float] = None
    strategy_max_drawdown_pct: Optional[float] = None
    benchmark_ticker: str = "^GSPC"
    benchmark_return_pct: Optional[float] = None
    benchmark_sharpe: Optional[float] = None
    out_of_sample_return_pct: Optional[float] = None
    out_of_sample_window: str = ""            # e.g. "2025-10-01 to 2026-08-14 (last 20%)"
    num_trades: int = 0
    notes: list[str] = Field(default_factory=list)


class EarningsCallSummary(BaseModel):
    """
    LLM summary of an earnings call transcript. Unlike every other LLM output
    in this schema module, this one is genuinely LLM-authored prose over a
    source document, not narration of pre-computed numbers — summarizing a
    fixed transcript is a bounded text task, not arithmetic, so it's outside
    the "no LLM does math" rule (see CLAUDE.md/AGENTS.md). Nothing here is a
    number the LLM derived itself.

    Source: Alpha Vantage's EARNINGS_CALL_TRANSCRIPT endpoint (available on
    the free API key), optionally enriched with Equibles' verified speaker
    roles / linked 8-K / extracted guidance when Equibles is running. See
    agents/stock/earnings_call_summarizer.py.
    """
    quarter: Optional[str] = None                       # e.g. "2026Q2"
    source: Literal["alpha_vantage"] = "alpha_vantage"
    key_highlights: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)
    management_tone: Literal["confident", "cautious", "mixed", "defensive", "neutral"] = "neutral"
    notable_qa: list[str] = Field(default_factory=list)
    linked_8k_url: Optional[str] = None                  # populated only when Equibles enrichment is available


class OptionsData(BaseModel):
    """
    Deterministic puts/calls volume, open-interest, and IV-skew snapshot from
    the nearest listed expiries. No LLM involved in computing any of this —
    see agents/stock/options_analyst.py.
    """
    put_call_volume_ratio: Optional[float] = None      # put volume / call volume, today
    put_call_ratio_30d_avg: Optional[float] = None      # trailing 30d average of the above
    unusual_call_activity: bool = False                 # ratio far below its 30d average
    unusual_put_activity: bool = False                  # ratio far above its 30d average
    iv_skew: Optional[float] = None                     # near-the-money put IV minus call IV
    dominant_call_strike: Optional[float] = None        # strike with the most call open interest
    dominant_put_strike: Optional[float] = None         # strike with the most put open interest
    nearest_expiry: Optional[str] = None
    total_call_volume: Optional[int] = None
    total_put_volume: Optional[int] = None
    summary: str = ""                                   # deterministic plain-English rollup


class ResearchBrief(BaseModel):
    ticker: str
    company_name: str
    as_of_date: str
    verdict: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    price_target_low: float
    price_target_high: float
    current_price: Optional[float] = None
    summary: str                              # 2-3 sentence executive summary
    bull_case: list[str]                      # 3-5 bullet points
    bear_case: list[str]                      # 3-5 bullet points
    key_risks: list[str]
    upcoming_catalysts: list[str]             # earnings, product launches, etc.
    fundamentals: ValuationSummary
    sentiment: SentimentSummary
    # Equibles-sourced fields — present when Equibles is running and depth="full"
    institutional: Optional[InstitutionalSnapshot] = None
    market_structure: Optional[MarketStructureData] = None
    technicals: Optional[TechnicalIndicators] = None
    signals: Optional[SignalSet] = None
    backtest: Optional[BacktestResult] = None
    options: Optional[OptionsData] = None
    sources: list[str] = Field(default_factory=list)


class StockPipelineInput(BaseModel):
    ticker: str
    depth: Literal["quick", "full"] = "full"
    provider: Optional[str] = None            # override LLM provider for this run


class TrendPoint(BaseModel):
    """One data point in a price or annual-financials trend series."""
    date: str                                 # ISO date
    close: Optional[float] = None             # price series
    revenue: Optional[float] = None           # annual financials series
    net_income: Optional[float] = None        # annual financials series


class VolatilityMetrics(BaseModel):
    """
    Daily-return volatility estimates — how much the price bounces around,
    computed deterministically (no LLM call) from ~1y of daily closes.
    """
    ewma_annualized_pct: Optional[float] = None            # RiskMetrics EWMA (lambda=0.94), recent-weighted
    garch_forecast_annualized_pct: Optional[float] = None  # GARCH(1,1) one-day-ahead forecast
    garch_long_run_annualized_pct: Optional[float] = None  # GARCH(1,1) unconditional long-run average
    interpretation: str = ""


class TrendData(BaseModel):
    """
    Five-year trend view: monthly price history + annual revenue/net income,
    plus a deterministically-computed (not LLM-generated) previous-year summary
    so change percentages can't be hallucinated.
    """
    ticker: str
    price_history: list[TrendPoint] = Field(default_factory=list)      # ~5y, monthly close
    annual_financials: list[TrendPoint] = Field(default_factory=list)  # revenue/net income per fiscal year
    previous_year_summary: str = ""
    volatility: Optional[VolatilityMetrics] = None
