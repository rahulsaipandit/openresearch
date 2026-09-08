"""Pydantic schemas for document parsing (LiteParse) and document-insights summarization."""

from typing import Optional, Union

from pydantic import BaseModel, Field


class ParsedTextItem(BaseModel):
    """One text run with its bounding box, as extracted by LiteParse."""
    text: str
    x: float
    y: float
    width: float
    height: float


class ParsedPage(BaseModel):
    page: int
    width: float
    height: float
    text: str                                    # full page text (for LLM input)
    text_items: list[ParsedTextItem] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    source_file: str
    pages: list[ParsedPage] = Field(default_factory=list)


class DocumentCitation(BaseModel):
    """
    A citation anchor: which document, which page, and a bounding box on
    that page. The box covers the run of text_items that best fuzzy-matches
    the LLM's cited quote (see DocumentInsightsAgent._find_best_span) when a
    good match is found; otherwise it falls back to the page's first text
    item as a "jump to page N" anchor. `document_name` makes each citation
    self-describing so a future multi-document answer wouldn't need an
    implicit single-document assumption.
    """
    document_name: str
    page: int
    x: float
    y: float
    width: float
    height: float
    excerpt: str


class XBRLFact(BaseModel):
    """
    A financial-statement line item sourced directly from a SEC filing's
    mandatory Inline XBRL tagging (via EdgarTools), not OCR'd from a PDF.
    The filer's own tag IS the source-grounding — every fact traces back to
    a specific concept + reporting period in a specific, citable filing —
    the same fact/context relationship Arelle's iXBRL Viewer visualizes
    (https://github.com/Arelle/ixbrl-viewer). Used as a fallback when PDF
    parsing fails for a SEC filing: exact structured data instead of a
    bounding-box guess. See DocumentInsightsAgent._try_xbrl_fallback.
    """
    concept: str            # fully-qualified XBRL element, e.g. "us-gaap_NetIncomeLoss"
    label: str               # filer's own statement label, e.g. "Net income"
    value: Union[float, str]
    unit: Optional[str] = None
    decimals: Optional[int] = None
    period_label: str        # e.g. "Annual: September 29, 2024 to September 27, 2025"
    statement_type: str      # "IncomeStatement" | "BalanceSheet" | "CashFlowStatement"
    filing_type: str         # "10-K" | "10-Q"
    filing_date: str
    accession_no: str
    filing_url: str          # the actual Inline XBRL HTML document on SEC EDGAR


class DocumentInsightAnswer(BaseModel):
    ticker: str
    document_name: str
    summary: str
    citations: list[DocumentCitation] = Field(default_factory=list)
    xbrl_facts: list[XBRLFact] = Field(default_factory=list)  # populated only via the XBRL fallback path
