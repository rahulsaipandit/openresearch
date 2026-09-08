"""
XBRLFallbackAgent — when PDF parsing fails for a SEC filing (LiteParse
unavailable, parse error, or empty text extraction), fetch the filing's
actual Inline XBRL data directly via EdgarTools instead of retrying/giving
up on the PDF.

Rationale (per user direction): the SEC has required Inline XBRL tagging of
financial statements since 2019 — the tagged HTML filing already carries a
source-grounding model of its own. Each fact ties back to its own tag via a
context/fact reference, the same fact-to-source relationship Arelle's
iXBRL Viewer visualizes (https://github.com/Arelle/ixbrl-viewer). That's a
stronger, exact source for financial-statement numbers than OCR'ing a
rendered PDF — no bounding-box heuristics needed, because the numbers are
already machine-readable and citable (concept + period + filing accession).

Scope: only the three primary financial statements (Income Statement,
Balance Sheet, Cash Flow Statement) — not the qualitative business/
risk-factors/MD&A prose, which SECIngestAgent already covers separately via
plain-text chunks for the SEC Insights Q&A pipeline.
"""

import logging

from schemas.document_insights import XBRLFact

logger = logging.getLogger(__name__)

_STATEMENT_TYPES = ("IncomeStatement", "BalanceSheet", "CashFlowStatement")
_FORMS = ("10-K", "10-Q")


def _select_period_key(periods: dict, period_of_report: str) -> str | None:
    """
    Pick the period key matching the filing's actual reporting period
    (`period_of_report`, e.g. "2025-09-27") rather than assuming dict
    insertion order — EdgarTools' `periods` dict mixes instant_ and
    duration_ keys in an order that isn't reliably "most recent first"
    for every statement type (verified: true for IncomeStatement/
    BalanceSheet, not for CashFlowStatement).
    """
    for key in periods:
        if key == f"instant_{period_of_report}":
            return key
        if key.startswith("duration_") and key.endswith(f"_{period_of_report}"):
            return key
    # Fallback: most primary statements are duration-based (income/cashflow);
    # a balance sheet (instant-only) would have matched exactly above.
    for key in periods:
        if key.startswith("duration_"):
            return key
    return next(iter(periods), None)


class XBRLFallbackAgent:
    def __init__(self, contact: str = "OpenResearch research@openresearch.local"):
        self.contact = contact

    def fetch_facts(self, ticker: str, form: str | None = None) -> list[XBRLFact]:
        """Fetch primary-statement XBRL facts from the ticker's latest 10-K/10-Q."""
        try:
            from edgar import Company, set_identity
            set_identity(self.contact)
        except Exception as e:
            logger.warning(f"EdgarTools not available: {e}")
            return []

        try:
            company = Company(ticker)
        except Exception as e:
            logger.warning(f"EdgarTools could not resolve company for {ticker}: {e}")
            return []

        for f in (form,) if form else _FORMS:
            try:
                filings = company.get_filings(form=f)
                if not filings or len(filings) == 0:
                    continue
                filing = filings.latest(1)
                if filing is None:
                    continue
                xb = filing.xbrl()
                facts = self._extract_facts(xb, filing, f)
                if facts:
                    return facts
            except Exception as e:
                logger.warning(f"XBRL fallback failed for {ticker} ({f}): {e}")

        return []

    def _extract_facts(self, xb, filing, form: str) -> list[XBRLFact]:
        filing_date  = str(getattr(filing, "filing_date", ""))
        accession_no = str(getattr(filing, "accession_no", ""))
        filing_url   = str(getattr(filing, "filing_url", ""))
        period_of_report = str(getattr(xb, "period_of_report", ""))

        facts: list[XBRLFact] = []
        for statement_type in _STATEMENT_TYPES:
            try:
                statement = xb.get_statement_by_type(statement_type)
            except Exception as e:
                logger.debug(f"No {statement_type} for {form} {accession_no}: {e}")
                continue
            if not statement:
                continue
            facts.extend(self._extract_statement_facts(
                statement, statement_type, form, filing_date, accession_no, filing_url, period_of_report,
            ))
        return facts

    def _extract_statement_facts(
        self, statement: dict, statement_type: str, form: str,
        filing_date: str, accession_no: str, filing_url: str, period_of_report: str,
    ) -> list[XBRLFact]:
        periods = statement.get("periods") or {}
        if not periods:
            return []
        period_key = _select_period_key(periods, period_of_report)
        if period_key is None:
            return []
        period_label = periods[period_key].get("label", period_key)

        facts = []
        for row in statement.get("data", []):
            if row.get("is_abstract") or not row.get("has_values"):
                continue
            value = row.get("values", {}).get(period_key)
            if value is None:
                continue
            facts.append(XBRLFact(
                concept=row.get("concept", ""),
                label=row.get("label") or row.get("concept", ""),
                value=value,
                unit=row.get("units", {}).get(period_key),
                decimals=row.get("decimals", {}).get(period_key),
                period_label=period_label,
                statement_type=statement_type,
                filing_type=form,
                filing_date=filing_date,
                accession_no=accession_no,
                filing_url=filing_url,
            ))
        return facts
