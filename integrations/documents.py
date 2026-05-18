"""
Document Loader — READ-ONLY.

Extracts text from Word (.docx) and PDF files in a folder.
Used to feed meeting notes, status reports, and strategy docs into the board pipeline.

PDF support:
  - Text-based PDFs: extracted directly with PyMuPDF (fast, no API call).
  - Scanned / image-based PDFs: auto-detected and OCR'd page-by-page using
    Claude vision via integrations.ocr.ScannedPDFOCR. Falls back gracefully
    if no Anthropic key is configured.

GUARDRAILS:
  - Only reads files. Never writes, modifies, deletes, or moves files.
  - Skips files larger than MAX_FILE_MB to avoid context overload.
  - Extracts plain text only — no binary data is sent to the LLM.
  - Respects a configurable file_extensions allowlist.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_FILE_MB     = 10
ALLOWED_EXTS    = {".docx", ".pdf", ".txt", ".md"}
MAX_TOTAL_CHARS = 50_000


class DocumentLoader:
    """
    Read-only document loader for Word (.docx) and PDF files.

    Automatically detects scanned PDFs and OCRs them if an Anthropic key is
    available. Pass ocr=None to disable OCR and skip scanned pages.

    Never writes, modifies, or deletes any files.
    """

    def __init__(
        self,
        folder_path: str,
        file_extensions: Optional[list[str]] = None,
        max_file_mb: float = MAX_FILE_MB,
        ocr=None,   # Optional[ScannedPDFOCR] — injected to avoid circular import
    ):
        self.folder_path    = Path(folder_path)
        self.allowed_exts   = {ext.lower() for ext in (file_extensions or list(ALLOWED_EXTS))}
        self.max_file_bytes = int(max_file_mb * 1024 * 1024)
        self._ocr           = ocr

        disallowed = self.allowed_exts - ALLOWED_EXTS
        if disallowed:
            raise ValueError(
                f"DocumentLoader only supports read-only text extraction from: "
                f"{sorted(ALLOWED_EXTS)}. Requested unsupported types: {sorted(disallowed)}"
            )

    def load_all(self) -> str:
        """
        Load all supported documents in the folder.

        Returns concatenated plain text, capped at MAX_TOTAL_CHARS.
        Scanned PDFs are OCR'd automatically when an OCR engine is configured.
        Never modifies any file.
        """
        if not self.folder_path.exists():
            logger.warning(f"Document folder not found: {self.folder_path}")
            return ""

        parts: list[str] = []
        total_chars = 0

        for path in sorted(self.folder_path.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.allowed_exts:
                continue
            if path.stat().st_size > self.max_file_bytes:
                logger.info(f"Skipping large file: {path.name} ({path.stat().st_size // 1024}KB)")
                continue

            text = self._extract(path)
            if not text:
                continue

            remaining = MAX_TOTAL_CHARS - total_chars
            if remaining <= 0:
                logger.info("Document text cap reached — remaining files skipped.")
                break

            trimmed = text[:remaining]
            parts.append(f"=== {path.name} ===\n{trimmed}")
            total_chars += len(trimmed)

        return "\n\n".join(parts)

    def load_file(self, file_path: str) -> str:
        """Load a single file. Returns plain text or empty string on failure."""
        path = Path(file_path)
        if path.suffix.lower() not in self.allowed_exts:
            raise ValueError(
                f"File type '{path.suffix}' is not supported. "
                f"Supported types: {sorted(ALLOWED_EXTS)}"
            )
        return self._extract(path)

    # ── Extractors ─────────────────────────────────────────────────────────────

    def _extract(self, path: Path) -> str:
        ext = path.suffix.lower()
        try:
            if ext == ".docx":
                return self._extract_docx(path)
            elif ext == ".pdf":
                return self._extract_pdf(path)
            elif ext in (".txt", ".md"):
                return self._extract_text(path)
        except Exception as e:
            logger.warning(f"Failed to extract {path.name}: {e}")
        return ""

    @staticmethod
    def _extract_docx(path: Path) -> str:
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "python-docx is required to read .docx files. "
                "Install it with: pip install python-docx"
            )
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    def _extract_pdf(self, path: Path) -> str:
        """
        Extract text from a PDF.

        Strategy:
          1. Try PyMuPDF standard text extraction.
          2. If PyMuPDF is unavailable, fall back to pypdf.
          3. If the result is sparse (scanned PDF) and an OCR engine is
             configured, use ScannedPDFOCR for page-level OCR.
        """
        # ── Attempt 1: PyMuPDF (preferred — faster, better layout handling) ──
        text = self._extract_pdf_pymupdf(path)

        # ── Attempt 2: pypdf fallback if PyMuPDF unavailable ─────────────────
        if text is None:
            text = self._extract_pdf_pypdf(path)

        if text is None:
            return ""

        # ── Attempt 3: OCR if text is too sparse (scanned PDF) ───────────────
        if self._is_sparse(text, path):
            if self._ocr is not None:
                logger.info(f"  {path.name}: detected as scanned — running OCR...")
                try:
                    text = self._ocr.extract(path)
                    logger.info(f"  {path.name}: OCR complete ({len(text)} chars extracted)")
                except Exception as e:
                    logger.warning(f"  {path.name}: OCR failed ({e}) — using sparse text as-is")
            else:
                logger.warning(
                    f"  {path.name}: detected as scanned PDF but no OCR engine is configured. "
                    f"Configure an Anthropic API key in config.yaml to enable OCR. "
                    f"Extracted text may be empty or incomplete."
                )

        return text

    @staticmethod
    def _extract_pdf_pymupdf(path: Path) -> Optional[str]:
        try:
            import fitz
            doc   = fitz.open(str(path))
            pages = [page.get_text("text") or "" for page in doc]
            return "\n\n".join(pages)
        except ImportError:
            return None   # PyMuPDF not installed — caller will try pypdf
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed for {path.name}: {e}")
            return ""

    @staticmethod
    def _extract_pdf_pypdf(path: Path) -> Optional[str]:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            pages  = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except ImportError:
            raise ImportError(
                "Neither PyMuPDF nor pypdf is installed. "
                "Install one with: pip install pymupdf  OR  pip install pypdf"
            )
        except Exception as e:
            logger.warning(f"pypdf extraction failed for {path.name}: {e}")
            return ""

    @staticmethod
    def _is_sparse(text: str, path: Path) -> bool:
        """Return True if the extracted text is too thin to be a real text PDF."""
        from integrations.ocr import MIN_CHARS_PER_PAGE
        # Estimate page count from file size (rough: ~50KB per page for scanned PDFs)
        try:
            size_kb       = path.stat().st_size / 1024
            est_pages     = max(1, int(size_kb / 50))
            avg_per_page  = len(text.strip()) / est_pages
            return avg_per_page < MIN_CHARS_PER_PAGE
        except Exception:
            return len(text.strip()) < MIN_CHARS_PER_PAGE

    @staticmethod
    def _extract_text(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> Optional["DocumentLoader"]:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        docs   = cfg.get("executive_board", {}).get("integrations", {}).get("documents", {})
        folder = docs.get("folder_path", "")
        if not folder:
            return None

        # Wire up OCR engine if enabled (default: true)
        ocr = None
        ocr_cfg = cfg.get("ocr", {})
        if ocr_cfg.get("enabled", True):
            try:
                from integrations.ocr import ScannedPDFOCR
                ocr = ScannedPDFOCR.from_config(config_path)
            except Exception as e:
                logger.warning(f"OCR engine init failed (scanned PDFs will not be readable): {e}")

        return cls(
            folder_path=folder,
            file_extensions=docs.get("file_extensions"),
            max_file_mb=docs.get("max_file_mb", MAX_FILE_MB),
            ocr=ocr,
        )
