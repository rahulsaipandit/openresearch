"""
DocumentInsightsAgent — summarizes an uploaded document (earnings call
transcript, analyst report, filing excerpt) for a ticker, citing back to
specific pages via LiteParse-extracted bounding-box anchors. Fills the
requirement #5 gap (earnings-call summarization) with an auditable citation
trail.

Citation granularity: the LLM is asked for a short verbatim quote per
citation, which is fuzzy-matched back against LiteParse's per-page
text_items to find the tightest bounding box that actually covers the cited
text (see _find_best_span). When no quote is given or nothing matches well
enough, it falls back to the page's first text item — a "jump to page N"
anchor rather than a precise highlight.

XBRL fallback: if LiteParse can't parse the upload at all (not installed,
parse error, or no extractable text) — which for a SEC filing PDF is often
just a bad OCR/render — try XBRLFallbackAgent instead of giving up. Most
SEC filings already carry Inline XBRL tagging with its own source-grounding
model (see xbrl_fallback.py), so a structured, exact answer is often
available even when the PDF itself won't parse. Deterministic (no LLM call)
since it's just formatting already-structured, already-cited data.
"""

import difflib
import logging
from pathlib import Path
from typing import Optional

from agents.api_utils import LLMClient, parse_llm_json
from agents.stock.xbrl_fallback import XBRLFallbackAgent
from schemas.document_insights import (
    DocumentCitation,
    DocumentInsightAnswer,
    ParsedDocument,
    ParsedPage,
    ParsedTextItem,
    XBRLFact,
)
from integrations import liteparse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are summarizing a financial document (earnings call transcript, \
analyst report, or filing excerpt) for an equity researcher. Extract key beats/misses, \
guidance, margin commentary, and management tone if present; otherwise summarize the \
document's key points plainly. Cite which page number(s) support each claim using \
[p<N>] markers (e.g. [p3]) inline in the summary. Ground every claim in the text \
provided — do not use outside knowledge.

For each page you cite, also give a short quote (5-15 words) copied VERBATIM from that \
page's text — this is used to locate the exact passage on the page, so it must be an \
exact substring of the source text, not a paraphrase.

Return ONLY valid JSON: {"summary": "<summary text with [p<N>] markers inline>", \
"citations": [{"page": <page number>, "quote": "<verbatim quote from that page>"}]}"""

# Below this fuzzy-match ratio, a candidate span isn't a confident enough
# match to trust as a precise bounding box — fall back to the page anchor.
MIN_MATCH_RATIO = 0.6
# How many consecutive text_items to try concatenating when searching for
# a quote that spans more than one item (LiteParse items are line/word
# granular, so a cited sentence often spans several).
MAX_SPAN_WINDOW = 12


def _normalize(s: str) -> str:
    return " ".join(s.split()).lower()


def _find_best_span(page: ParsedPage, quote: str) -> tuple[list[ParsedTextItem], float]:
    """
    Find the run of consecutive text_items on `page` whose concatenated text
    best matches `quote`. Returns (matched_items, ratio); matched_items is
    empty if nothing clears MIN_MATCH_RATIO.
    """
    items = page.text_items
    if not items or not quote:
        return [], 0.0

    norm_quote = _normalize(quote)
    if not norm_quote:
        return [], 0.0

    # Cheap common case: the quote sits entirely inside one item's text.
    for item in items:
        if norm_quote in _normalize(item.text):
            return [item], 1.0

    # Otherwise slide a window of consecutive items and fuzzy-match the
    # concatenation against the quote. Each window is built by extending the
    # previous size's normalized text by one item, instead of re-joining and
    # re-normalizing every item in the window from scratch each time — that
    # re-normalization was the O(window_size) cost repeated for every
    # (start, size) pair, i.e. O(n * MAX_SPAN_WINDOW^2) on a densely
    # tokenized page. Building incrementally makes it O(n * MAX_SPAN_WINDOW).
    # (`_normalize(" ".join(texts))` and `" ".join(_normalize(t) for t in texts)`
    # produce identical output — _normalize already collapses all whitespace,
    # so pre-normalizing each item before joining doesn't change the result.)
    best_items: list[ParsedTextItem] = []
    best_ratio = 0.0
    max_window = min(len(items), MAX_SPAN_WINDOW)
    for start in range(len(items)):
        window_text = ""
        for size in range(1, max_window + 1):
            end = start + size
            if end > len(items):
                break
            piece = _normalize(items[end - 1].text)
            window_text = f"{window_text} {piece}" if window_text else piece
            ratio = difflib.SequenceMatcher(None, norm_quote, window_text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_items = items[start:end]

    return (best_items, best_ratio) if best_ratio >= MIN_MATCH_RATIO else ([], best_ratio)


def _union_bbox(items: list[ParsedTextItem]) -> tuple[float, float, float, float]:
    """Bounding box covering every item in `items` (x, y, width, height)."""
    x0 = min(it.x for it in items)
    y0 = min(it.y for it in items)
    x1 = max(it.x + it.width for it in items)
    y1 = max(it.y + it.height for it in items)
    return x0, y0, x1 - x0, y1 - y0


# Common us-gaap tags for the handful of headline figures worth calling out
# by name; filers vary in which synonym they use for the same concept (e.g.
# revenue), so each entry lists the ones actually seen in practice, tried in
# order. Anything not in this list still shows up in `xbrl_facts` — this is
# only for picking a few figures to name in the plain-text `summary`.
_PRIORITY_CONCEPTS: dict[str, tuple[str, ...]] = {
    "Revenue": (
        "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap_RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap_Revenues",
    ),
    "Net Income": ("us-gaap_NetIncomeLoss",),
    "Diluted EPS": ("us-gaap_EarningsPerShareDiluted",),
    "Total Assets": ("us-gaap_Assets",),
    "Total Liabilities": ("us-gaap_Liabilities",),
    "Operating Cash Flow": ("us-gaap_NetCashProvidedByUsedInOperatingActivities",),
}


def _format_xbrl_value(value, unit: Optional[str]) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    if unit == "usd":
        if abs(value) >= 1e9:
            return f"${value / 1e9:.2f}B"
        if abs(value) >= 1e6:
            return f"${value / 1e6:.2f}M"
        return f"${value:,.2f}"
    if unit == "usdPerShare":
        return f"${value:.2f}"
    if unit == "shares":
        return f"{value:,.0f} shares"
    return f"{value:,.2f}" if value != int(value) else f"{int(value):,}"


def _format_xbrl_summary(facts: list[XBRLFact]) -> str:
    """Deterministic plain-text summary of the fallback facts — no LLM call,
    since it's just formatting already-structured, already-cited data."""
    if not facts:
        return ""

    header = (
        f"PDF parsing was unavailable, so the figures below were extracted directly from this "
        f"company's {facts[0].filing_type} Inline XBRL tagging (filed {facts[0].filing_date}), "
        f"not from the uploaded file. See `xbrl_facts` for the full set with source references."
    )

    by_concept = {f.concept: f for f in facts}
    lines = []
    for label, concepts in _PRIORITY_CONCEPTS.items():
        for concept in concepts:
            if concept in by_concept:
                fact = by_concept[concept]
                lines.append(f"{label}: {_format_xbrl_value(fact.value, fact.unit)} ({fact.period_label})")
                break

    if not lines:
        # None of the priority concepts were tagged under a recognized name
        # (uncommon) — fall back to whatever facts we do have.
        lines = [f"{f.label}: {_format_xbrl_value(f.value, f.unit)} ({f.period_label})" for f in facts[:10]]

    return header + "\n" + "\n".join(lines)


class DocumentInsightsAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False, xbrl_fallback: Optional[XBRLFallbackAgent] = None):
        self.llm           = llm
        self.verbose       = verbose
        self.xbrl_fallback = xbrl_fallback

    def summarize(
        self, ticker: str, pdf_path: str, max_pages: int = 30, document_name: str | None = None
    ) -> DocumentInsightAnswer:
        ticker = ticker.upper().strip()
        # Prefer the caller-supplied original filename (server.py passes the
        # upload's real name) — pdf_path itself is often a throwaway temp
        # path (e.g. /tmp/tmpabc123.pdf) that means nothing to a user.
        doc_name = document_name or Path(pdf_path).name

        if not liteparse.is_available():
            return self._fallback_or_error(
                ticker, doc_name,
                "LiteParse CLI is not installed — run `npm install` in tools/liteparse/.",
            )

        try:
            doc: ParsedDocument = liteparse.parse_pdf(pdf_path, max_pages=max_pages)
        except Exception as e:
            logger.warning(f"LiteParse failed for {pdf_path}: {e}")
            return self._fallback_or_error(ticker, doc_name, f"Could not parse this document: {e}")

        if not doc.pages or not any(p.text.strip() for p in doc.pages):
            return self._fallback_or_error(
                ticker, doc_name, "Could not extract any text from this document."
            )

        if self.verbose:
            print(f"  [DocumentInsights] Summarizing {len(doc.pages)}-page document for {ticker}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(doc)}],
            max_tokens=1200,
        )

        return parse_llm_json(
            raw, "DocumentInsights",
            builder=lambda data: DocumentInsightAnswer(
                ticker=ticker, document_name=doc_name,
                summary=data.get("summary", ""),
                citations=self._build_citations(doc, doc_name, data.get("citations", [])),
            ),
            fallback=lambda: DocumentInsightAnswer(
                ticker=ticker, document_name=doc_name,
                summary=raw.strip() or "Unable to summarize this document.", citations=[],
            ),
        )

    def _fallback_or_error(
        self, ticker: str, doc_name: str, error_summary: str
    ) -> DocumentInsightAnswer:
        """Try the XBRL fallback (§ module docstring); if it can't help either,
        return the plain error message. Shared by all three ways summarize()
        can fail before ever calling the LLM (LiteParse missing, LiteParse
        raised, or LiteParse returned no text) — they previously each
        hand-copied this same try-fallback-else-error shape."""
        fallback = self._try_xbrl_fallback(ticker)
        if fallback:
            return fallback
        return DocumentInsightAnswer(
            ticker=ticker, document_name=doc_name, summary=error_summary, citations=[]
        )

    def _try_xbrl_fallback(self, ticker: str) -> Optional[DocumentInsightAnswer]:
        """Attempt the XBRL fallback; returns None (never raises) if no
        fallback agent is configured or no facts could be fetched, so
        callers can cleanly fall through to the original error message."""
        if not self.xbrl_fallback:
            return None
        try:
            facts = self.xbrl_fallback.fetch_facts(ticker)
        except Exception as e:
            logger.warning(f"XBRL fallback failed for {ticker}: {e}")
            return None
        if not facts:
            return None

        doc_name = f"{facts[0].filing_type} filed {facts[0].filing_date} (SEC EDGAR, Inline XBRL)"
        return DocumentInsightAnswer(
            ticker=ticker, document_name=doc_name,
            summary=_format_xbrl_summary(facts),
            citations=[], xbrl_facts=facts,
        )

    def _build_prompt(self, doc: ParsedDocument) -> str:
        lines = []
        for page in doc.pages:
            if page.text.strip():
                lines.append(f"[Page {page.page}]\n{page.text[:2000]}")
        return "\n\n".join(lines)

    def _build_citations(
        self, doc: ParsedDocument, document_name: str, citations_data: list
    ) -> list[DocumentCitation]:
        by_page = {p.page: p for p in doc.pages}
        citations = []
        for c in citations_data:
            page_num = c.get("page")
            quote = c.get("quote", "")
            page = by_page.get(page_num)
            if not page:
                continue

            matched_items, ratio = _find_best_span(page, quote)
            if matched_items:
                x, y, width, height = _union_bbox(matched_items)
                excerpt = quote or " ".join(it.text for it in matched_items)
            else:
                # No confident span match — fall back to the page's first
                # text item as a coarse "jump to page N" anchor.
                anchor = page.text_items[0] if page.text_items else None
                x = anchor.x if anchor else 0.0
                y = anchor.y if anchor else 0.0
                width = anchor.width if anchor else 0.0
                height = anchor.height if anchor else 0.0
                excerpt = page.text[:300]

            citations.append(DocumentCitation(
                document_name=document_name,
                page=page_num,
                x=x, y=y, width=width, height=height,
                excerpt=excerpt,
            ))
        return citations
