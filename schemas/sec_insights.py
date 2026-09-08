"""Pydantic schemas for SEC Insights (filing Q&A with local semantic search)."""

from pydantic import BaseModel, Field


class SECChunk(BaseModel):
    """One chunk of SEC filing text, ready for local embedding."""
    ticker: str
    filing_type: str      # "10-K" | "10-Q"
    section: str          # "business" | "risk_factors" | "management_discussion"
    filing_date: str
    text: str


class SECCitation(BaseModel):
    filing_type: str
    section: str
    filing_date: str
    excerpt: str


class SECAnswer(BaseModel):
    ticker: str
    question: str
    answer: str
    citations: list[SECCitation] = Field(default_factory=list)
