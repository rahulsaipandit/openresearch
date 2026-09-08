"""
SECIngestAgent — fetches a company's latest 10-K/10-Q from SEC EDGAR via
EdgarTools and splits key sections (business, risk factors, MD&A) into
chunks for local embedding (see SECVectorStore).

EdgarTools was scoped in requirements.md as a fallback data source if
Equibles isn't set up — used directly here since Equibles' full-text search
isn't exposed as section-level filing text through our MCP client.
"""

import logging

from schemas.sec_insights import SECChunk

logger = logging.getLogger(__name__)

_CHUNK_SIZE_CHARS = 1200
_SECTIONS = [
    ("business", "business"),
    ("risk_factors", "risk_factors"),
    ("management_discussion", "management_discussion"),
]
_FORMS = ("10-K", "10-Q")


class SECIngestAgent:
    def __init__(self, contact: str = "OpenResearch research@openresearch.local"):
        self.contact = contact

    def fetch_chunks(self, ticker: str) -> list[SECChunk]:
        try:
            from edgar import Company, set_identity
            set_identity(self.contact)
        except Exception as e:
            logger.warning(f"EdgarTools not available: {e}")
            return []

        chunks: list[SECChunk] = []
        try:
            company = Company(ticker)
        except Exception as e:
            logger.warning(f"EdgarTools could not resolve company for {ticker}: {e}")
            return []

        for form in _FORMS:
            try:
                filings = company.get_filings(form=form)
                if not filings or len(filings) == 0:
                    continue
                filing = filings.latest(1)
                if filing is None:
                    continue

                filing_date = str(getattr(filing, "filing_date", ""))
                doc = filing.obj()

                for attr, section_name in _SECTIONS:
                    text = getattr(doc, attr, None)
                    if not text or not isinstance(text, str):
                        continue
                    chunks.extend(self._chunk_text(ticker, form, section_name, filing_date, text))
            except Exception as e:
                logger.warning(f"SEC ingest failed for {ticker} ({form}): {e}")

        return chunks

    def _chunk_text(self, ticker: str, form: str, section: str, filing_date: str, text: str) -> list[SECChunk]:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks: list[SECChunk] = []
        buf = ""
        for p in paragraphs:
            if buf and len(buf) + len(p) > _CHUNK_SIZE_CHARS:
                chunks.append(SECChunk(
                    ticker=ticker.upper(), filing_type=form, section=section,
                    filing_date=filing_date, text=buf,
                ))
                buf = ""
            buf = f"{buf}\n{p}" if buf else p
        if buf:
            chunks.append(SECChunk(
                ticker=ticker.upper(), filing_type=form, section=section,
                filing_date=filing_date, text=buf,
            ))
        return chunks
