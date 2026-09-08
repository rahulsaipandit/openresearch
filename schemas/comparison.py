"""Pydantic schemas for two-stock side-by-side comparison."""

from pydantic import BaseModel, Field

from schemas.stock import ResearchBrief


class ComparisonVerdict(BaseModel):
    category: str      # "Fundamentals" | "Growth" | "Valuation" | "Sentiment"
    winner: str        # ticker of the stronger stock in this category, or "Even"
    rationale: str


class ComparisonBrief(BaseModel):
    ticker_a: str
    ticker_b: str
    overall_lean: str  # ticker that comes out ahead overall, or "Even"
    summary: str
    categories: list[ComparisonVerdict] = Field(default_factory=list)
    brief_a: ResearchBrief
    brief_b: ResearchBrief
