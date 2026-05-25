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
    sources: list[str] = Field(default_factory=list)


class StockPipelineInput(BaseModel):
    ticker: str
    depth: Literal["quick", "full"] = "full"
    provider: Optional[str] = None            # override LLM provider for this run
