"""
Per-page document parsing + chunking for the interview-memory RAG pipeline.

Unlike integrations/documents.py's DocumentLoader (which concatenates every
file in a folder into one flattened blob — fine for the executive-board
digest use case it was built for), this module keeps per-file, per-page
boundaries intact, because per-document selection and page-level citation
(docs/designInterviewTool.md "Full Plan: Per-Document Selection + Source
Traceability") depend on knowing exactly which page a chunk came from.

Every accepted file is verified against its real byte content via
integrations/file_type_check.py before parsing — the same magika guard
DocumentLoader uses, just wired into this path too (it previously wasn't).
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md"}

_CHUNK_CHARS = 1600      # ~300-500 tokens
_CHUNK_OVERLAP = 200
_PSEUDO_PAGE_PARAGRAPHS = 25   # DOCX: paragraphs per pseudo-page
_PSEUDO_PAGE_LINES = 40        # TXT/MD: lines per pseudo-page


@dataclass
class PageText:
    page_number: int
    text: str


@dataclass
class Chunk:
    page_number: int
    chunk_index: int
    text: str


class UnsupportedDocumentError(ValueError):
    pass


def extract_pages(path: Path) -> list[PageText]:
    """Parse a file into page-boundaried text. Raises UnsupportedDocumentError
    if the extension isn't supported or the real content doesn't match it."""
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise UnsupportedDocumentError(f"Unsupported file type: {ext}")

    from integrations.file_type_check import verify_extension

    data = path.read_bytes()
    ok, detected = verify_extension(data, ext)
    if not ok:
        raise UnsupportedDocumentError(
            f"Content does not match '{ext}' extension (detected: {detected})."
        )

    if ext == ".pdf":
        return _extract_pdf_pages(path)
    if ext == ".docx":
        return _extract_docx_pages(path)
    return _extract_text_pages(path)


def _extract_pdf_pages(path: Path) -> list[PageText]:
    try:
        import fitz
    except ImportError as e:
        raise UnsupportedDocumentError(
            "PyMuPDF (fitz) is required to parse PDFs. Install with: pip install pymupdf"
        ) from e

    doc = fitz.open(str(path))
    pages = []
    all_sparse = True
    for i, page in enumerate(doc, start=1):
        text = (page.get_text("text") or "").strip()
        if text:
            all_sparse = False
        pages.append(PageText(page_number=i, text=text))

    if all_sparse:
        pages = _try_ocr_pages(path, pages)
    return pages


def _try_ocr_pages(path: Path, pages: list[PageText]) -> list[PageText]:
    """Scanned PDF fallback — reuses the existing ScannedPDFOCR engine
    (already used by agents/realestate/document_ingestion.py) rather than
    re-implementing OCR. Falls back to the (empty) sparse pages if OCR isn't
    configured or fails, matching DocumentLoader's existing behavior.

    ScannedPDFOCR.extract() returns one concatenated string with page
    boundaries already collapsed (it joins per-page text with "\\n\\n" and
    drops blank pages) — there's no page marker to split back out. So a
    scanned document is indexed as a single page 1 chunk-set; per-page
    citation degrades gracefully to whole-document citation for this case
    rather than guessing at page boundaries that aren't actually there.
    """
    try:
        from integrations.ocr import ScannedPDFOCR

        ocr = ScannedPDFOCR.from_config()
        if ocr is None:
            logger.warning(f"{path.name}: scanned-PDF OCR not configured — using sparse text.")
            return pages
        text = ocr.extract(path)
    except Exception as e:
        logger.warning(f"{path.name}: scanned-PDF OCR failed ({e}) — using sparse text as-is.")
        return pages

    return [PageText(page_number=1, text=text.strip())]


def _extract_docx_pages(path: Path) -> list[PageText]:
    try:
        from docx import Document
    except ImportError as e:
        raise UnsupportedDocumentError(
            "python-docx is required to parse .docx files. Install with: pip install python-docx"
        ) from e

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

    pages = []
    for i, start in enumerate(range(0, len(paragraphs), _PSEUDO_PAGE_PARAGRAPHS), start=1):
        group = paragraphs[start : start + _PSEUDO_PAGE_PARAGRAPHS]
        pages.append(PageText(page_number=i, text="\n".join(group)))
    return pages or [PageText(page_number=1, text="")]


def _extract_text_pages(path: Path) -> list[PageText]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pages = []
    for i, start in enumerate(range(0, len(lines), _PSEUDO_PAGE_LINES), start=1):
        group = lines[start : start + _PSEUDO_PAGE_LINES]
        pages.append(PageText(page_number=i, text="\n".join(group)))
    return pages or [PageText(page_number=1, text="")]


def chunk_pages(pages: list[PageText]) -> list[Chunk]:
    """Split each page's text into overlapping windows, preserving page_number.
    A short page (the common case) becomes exactly one chunk."""
    chunks: list[Chunk] = []
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        if len(text) <= _CHUNK_CHARS:
            chunks.append(Chunk(page_number=page.page_number, chunk_index=0, text=text))
            continue
        start = 0
        idx = 0
        while start < len(text):
            window = text[start : start + _CHUNK_CHARS]
            chunks.append(Chunk(page_number=page.page_number, chunk_index=idx, text=window))
            idx += 1
            start += _CHUNK_CHARS - _CHUNK_OVERLAP
    return chunks
