"""
LiteParse integration — shells out to the locally-installed @llamaindex/liteparse
CLI (tools/liteparse/, installed via `npm install`) to extract text with
bounding-box coordinates from PDFs.

LiteParse is Apache-2.0, standalone (single dependency: commander), and was
verified directly against its actual npm package and CLI output — not just
the vendor blog's claims — before being adopted here (see
Initial_requirement_collection.md). It's a Node.js CLI tool, not a Python
library, so this integration shells out and parses its JSON output rather
than importing it in-process.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from schemas.document_insights import ParsedDocument, ParsedPage, ParsedTextItem

logger = logging.getLogger(__name__)

_TOOL_DIR     = Path(__file__).resolve().parent.parent / "tools" / "liteparse"
_BIN_WINDOWS  = _TOOL_DIR / "node_modules" / ".bin" / "liteparse.cmd"
_BIN_POSIX    = _TOOL_DIR / "node_modules" / ".bin" / "liteparse"


def _resolve_binary() -> Path:
    if _BIN_WINDOWS.exists():
        return _BIN_WINDOWS
    if _BIN_POSIX.exists():
        return _BIN_POSIX
    raise FileNotFoundError(
        "LiteParse CLI not found — run `npm install` in tools/liteparse/ first."
    )


def is_available() -> bool:
    try:
        _resolve_binary()
        return True
    except FileNotFoundError:
        return False


def parse_pdf(pdf_path: str | Path, max_pages: Optional[int] = None, timeout: int = 120) -> ParsedDocument:
    """
    Parse a PDF via the local LiteParse CLI, returning per-page text plus
    bounding-box text items (for citation anchoring).

    Raises FileNotFoundError if the CLI isn't installed, RuntimeError if the
    subprocess exits non-zero.
    """
    binary   = _resolve_binary()
    pdf_path = Path(pdf_path)

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.json"
        cmd = [str(binary), "parse", str(pdf_path), "--format", "json", "-o", str(out_path)]
        if max_pages:
            cmd += ["--max-pages", str(max_pages)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"LiteParse failed (exit {result.returncode}): {result.stderr[:500]}")

        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)

    pages = []
    for p in data.get("pages", []):
        items = [
            ParsedTextItem(
                text=it.get("text", ""),
                x=it.get("x", 0.0), y=it.get("y", 0.0),
                width=it.get("width", 0.0), height=it.get("height", 0.0),
            )
            for it in p.get("text_items", [])
        ]
        pages.append(ParsedPage(
            page=p.get("page", 0), width=p.get("width", 0), height=p.get("height", 0),
            text=p.get("text", ""), text_items=items,
        ))

    return ParsedDocument(source_file=str(pdf_path), pages=pages)
