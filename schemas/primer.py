"""
Pydantic schemas for the Research Primer — a richer, multi-section document
loosely modeled on institutional "20/60/20" research primers (baseload facts,
deep-dive debate structure, adversarial review, underwriting synthesis), but
scoped down to a single-pass pipeline rather than a multi-day, per-unknown
deep-dive research process. See requirements.md for the scoping decision.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field

from schemas.stock import ResearchBrief, TrendData


class BusinessFoundation(BaseModel):
    """Company/industry narrative — the 'Business Foundation' baseload section."""
    overview: str                                   # what the company does, business model in plain terms
    revenue_model: str                              # how revenue actually gets generated
    key_segments: list[str] = Field(default_factory=list)
    unit_economics_notes: str = ""                   # margins, customer economics, cost structure notes


class DriverTreeItem(BaseModel):
    """One identified value driver for the stock."""
    driver: str
    direction: Literal["tailwind", "headwind", "mixed"]
    confidence: Literal["high", "medium", "low"]
    note: str


class DebateItem(BaseModel):
    """One open question/unknown the market is debating about this stock."""
    question: str
    bull_view: str
    bear_view: str
    what_would_resolve_it: str                       # what data/event would settle the debate


class AdversarialReview(BaseModel):
    """Stress-test pass over the existing bull/bear case — the 'Adversarial Review' section."""
    integrated_bear_case: str                        # the strongest coherent bear thesis, reconciling all debates
    reconciliation_notes: list[str] = Field(default_factory=list)   # where the bull case may be overstated
    numeric_sanity_checks: list[str] = Field(default_factory=list)  # e.g. "implied upside vs. historical multiple range"


class ResearchPrimer(BaseModel):
    """
    Full primer: wraps the existing ResearchBrief + TrendData ("baseload")
    plus new business-foundation, driver-tree/debate-map, and adversarial
    review sections, closed out with a short underwriting synthesis.
    """
    ticker: str
    company_name: str
    as_of_date: str

    research_brief: ResearchBrief                    # baseload: fundamentals, sentiment, verdict
    trend: TrendData                                 # baseload: 5yr trend + previous-year summary

    business_foundation: BusinessFoundation
    driver_tree: list[DriverTreeItem] = Field(default_factory=list)
    debate_map: list[DebateItem] = Field(default_factory=list)
    adversarial_review: AdversarialReview

    underwriting_summary: str = ""                   # short synthesis: estimates -> recommendation


class PrimerPipelineInput(BaseModel):
    ticker: str
    depth: Literal["quick", "full"] = "full"
