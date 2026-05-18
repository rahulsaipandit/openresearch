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


class ResearchBrief(BaseModel):
    ticker: str
    company_name: str
    as_of_date: str
    verdict: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    price_target_low: float
    price_target_high: float
    current_price: Optional[float] = None
    summary: str                        # 2-3 sentence executive summary
    bull_case: list[str]                # 3-5 bullet points
    bear_case: list[str]                # 3-5 bullet points
    key_risks: list[str]
    upcoming_catalysts: list[str]       # earnings, product launches, etc.
    fundamentals: ValuationSummary
    sentiment: SentimentSummary
    sources: list[str] = Field(default_factory=list)


class StockPipelineInput(BaseModel):
    ticker: str
    depth: Literal["quick", "full"] = "full"
    provider: Optional[str] = None      # override LLM provider for this run
