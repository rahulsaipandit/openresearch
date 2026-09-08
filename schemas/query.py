"""Pydantic schemas for the natural-language Query Router."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

Intent = Literal["single_analysis", "comparison", "watchlist_add", "unknown"]


class CompanyGuess(BaseModel):
    """Raw LLM guess for a company mentioned in a free-text query — not yet verified."""
    name: str
    likely_ticker: Optional[str] = None
    exchange_guess: Optional[str] = None


class QueryIntent(BaseModel):
    """Raw structured output from the LLM extraction call, before ticker verification."""
    intent: Intent = "unknown"
    companies: list[CompanyGuess] = Field(default_factory=list)
    depth: Literal["quick", "full"] = "full"


class ResolvedCompany(BaseModel):
    """A company whose ticker was verified against a live data source (yfinance)."""
    name: str
    ticker: str


class QueryRouterResult(BaseModel):
    """
    Final result returned to the caller. If clarification_needed is True, no
    pipeline should be run — the caller should surface clarification_question
    to the user instead of proceeding on an unverified or missing ticker.
    """
    intent: Intent
    resolved: list[ResolvedCompany] = Field(default_factory=list)
    depth: Literal["quick", "full"] = "full"
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
