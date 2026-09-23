"""
Pydantic schemas for the Opportunity Radar — cross-ticker/sector theme
detection over the user's watchlist. See docs/Stocks/designStock_DashboardUI.md
and agents/stock/opportunity_radar.py for the deterministic scoring behind
these fields; the LLM only fills `description`.
"""

from typing import Literal
from pydantic import BaseModel, Field


class ThemeEvidence(BaseModel):
    """One headline that contributed to a theme's detection — the grounding
    the LLM's description is restricted to, and what a human can check."""
    ticker: str
    title: str
    source: str = ""
    published_at: str = ""
    url: str = ""


class ThemeTickerStance(BaseModel):
    """
    A watchlist ticker whose headlines mentioned this theme, and a
    deterministic keyword-lexicon read of whether those headlines leaned
    positive or negative for it. This is a heuristic, not a sentiment model —
    see agents/stock/opportunity_radar.py's _classify_stance().
    """
    ticker: str
    stance: Literal["benefit", "pressured", "mentioned"]
    mention_count: int


class OpportunityTheme(BaseModel):
    theme: str                                     # the extracted phrase, e.g. "AI Capex"
    strength_score: float                          # 0-100, deterministic — see opportunity_radar.py
    description: str                                # LLM narration, grounded only in `evidence`
    tickers: list[ThemeTickerStance] = Field(default_factory=list)
    evidence: list[ThemeEvidence] = Field(default_factory=list)


class OpportunityRadarResult(BaseModel):
    generated_at: str                               # ISO date the batch job produced this snapshot
    universe: list[str] = Field(default_factory=list)  # tickers scanned — currently the watchlist
    themes: list[OpportunityTheme] = Field(default_factory=list)
