"""
Scanned PDF OCR — READ-ONLY.

Detects whether a PDF is image-based (scanned) and, if so, renders each page
to an image with PyMuPDF and uses Claude vision to extract the text.

Why Claude vision instead of Tesseract:
  - Tesseract requires a system binary install that may not be present.
  - Claude vision handles mixed layouts (tables, two-column, handwriting)
    more accurately than Tesseract for typical business documents.
  - Uses claude-haiku (fast + cheap) for OCR — not the primary reasoning model.

GUARDRAILS:
  - Only reads files. Never writes, modifies, or deletes anything.
  - Images are rendered in memory and sent to the API. Nothing is written to disk
    unless the caller explicitly requests debug image export.
  - Pages yielding < MIN_CHARS_PER_PAGE from regular text extraction are treated
    as scanned and sent through OCR. Pages with sufficient text skip the API call.
"""

import base64
import io
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# If a page yields fewer than this many characters from standard text extraction,
# it is treated as a scanned/image page and sent to OCR.
MIN_CHARS_PER_PAGE = 50

# Vision model used for OCR — Haiku is fast, cheap, and accurate for text extraction.
DEFAULT_OCR_MODEL = "claude-haiku-4-5-20251001"

# Render DPI — 200 dpi gives clear text without excessive image size.
RENDER_DPI = 200
RENDER_SCALE = RENDER_DPI / 72  # PyMuPDF uses 72 dpi as base


class ScannedPDFOCR:
    """
    Detects and OCRs scanned (image-based) PDF files.

    Usage:
        ocr = ScannedPDFOCR.from_config("config.yaml")
        text = ocr.extract(Path("scan.pdf"))

    Falls back gracefully if:
      - PyMuPDF is not installed
      - No Anthropic API key is configured
      - A page renders to an empty image
    """

    def __init__(self, api_key: str, model: str = DEFAULT_OCR_MODEL, dpi: int = RENDER_DPI):
        if not api_key:
            raise ValueError("ScannedPDFOCR requires an Anthropic API key.")
        self._api_key = api_key
        self._model   = model
        self._scale   = dpi / 72

    # ── Public ─────────────────────────────────────────────────────────────────

    @staticmethod
    def is_scanned(pdf_path: Path, sample_pages: int = 3) -> bool:
        """
        Return True if the PDF appears to be image-based (scanned).

        Checks up to `sample_pages` pages. If the average extracted text is below
        MIN_CHARS_PER_PAGE, the PDF is considered scanned.
        """
        try:
            import fitz
        except ImportError:
            logger.debug("PyMuPDF not installed — cannot detect scanned PDFs.")
            return False

        try:
            doc = fitz.open(str(pdf_path))
            pages_to_check = min(sample_pages, len(doc))
            if pages_to_check == 0:
                return False

            total_chars = sum(
                len(doc[i].get_text("text") or "")
                for i in range(pages_to_check)
            )
            avg_chars = total_chars / pages_to_check
            return avg_chars < MIN_CHARS_PER_PAGE
        except Exception as e:
            logger.warning(f"Scanned PDF detection failed for {pdf_path.name}: {e}")
            return False

    def extract(self, pdf_path: Path) -> str:
        """
        Extract text from a PDF, using OCR for pages with insufficient text.

        For each page:
          1. Attempt standard text extraction via PyMuPDF.
          2. If the extracted text is too sparse, render the page to a PNG image
             and use Claude vision to read it.
          3. Concatenate all page texts.

        Returns plain text. Never modifies the source file.
        """
        try:
            import fitz
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for scanned PDF OCR. "
                "Install it with: pip install pymupdf"
            )

        doc   = fitz.open(str(pdf_path))
        pages: list[str] = []

        for page_num in range(len(doc)):
            page      = doc[page_num]
            text      = page.get_text("text") or ""
            char_count = len(text.strip())

            if char_count >= MIN_CHARS_PER_PAGE:
                pages.append(text)
                logger.debug(f"  Page {page_num + 1}: text extracted ({char_count} chars)")
            else:
                logger.debug(f"  Page {page_num + 1}: sparse text ({char_count} chars) — using OCR")
                ocr_text = self._ocr_page(page)
                pages.append(ocr_text)

        return "\n\n".join(p for p in pages if p.strip())

    # ── Private ─────────────────────────────────────────────────────────────────

    def _ocr_page(self, page) -> str:
        """Render a PyMuPDF page to PNG and OCR it with Claude vision."""
        import fitz

        mat = fitz.Matrix(self._scale, self._scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")

        return self._claude_vision_ocr(png_bytes)

    def _claude_vision_ocr(self, png_bytes: bytes) -> str:
        """Send a PNG image to Claude vision and return the extracted text."""
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic SDK is required for vision OCR. "
                "Install it with: pip install anthropic"
            )

        client     = anthropic.Anthropic(api_key=self._api_key)
        image_data = base64.standard_b64encode(png_bytes).decode("utf-8")

        message = client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": "image/png",
                            "data":       image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract all text from this document page exactly as it appears. "
                            "Preserve headings, bullet points, numbered lists, and table structure. "
                            "Return only the extracted text — no commentary, no explanations."
                        ),
                    },
                ],
            }],
        )
        return message.content[0].text if message.content else ""

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> Optional["ScannedPDFOCR"]:
        """
        Build a ScannedPDFOCR from config.yaml.

        Looks for an Anthropic API key in llm.provider_chain first,
        then falls back to ocr.api_key if explicitly set.
        Returns None if no key is found (OCR will be skipped).
        """
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        # Try to find an anthropic key in the provider chain
        api_key = ""
        for entry in cfg.get("llm", {}).get("provider_chain", []):
            if entry.get("provider") == "anthropic" and entry.get("api_key"):
                api_key = entry["api_key"]
                break

        # Explicit OCR override key takes precedence
        ocr_cfg = cfg.get("ocr", {})
        api_key = ocr_cfg.get("api_key") or api_key

        if not api_key:
            logger.info("No Anthropic key found — scanned PDF OCR will be skipped.")
            return None

        return cls(
            api_key=api_key,
            model=ocr_cfg.get("model", DEFAULT_OCR_MODEL),
            dpi=ocr_cfg.get("dpi", RENDER_DPI),
        )
