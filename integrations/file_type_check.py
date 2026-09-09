"""
Central file-content verification — Google Magika (AI file-type detection
from actual bytes), used to guard every place an external/user-supplied file
enters the system instead of trusting its filename extension or a
client-declared MIME type.

Call sites:
  - server.py's /api/stock-document-insights upload (checks the uploaded
    bytes are really a PDF before handing them to LiteParse).
  - agents/api_utils.py's image-attachment path (checks an ImageAttachment's
    base64 bytes really match its declared media_type before it's forwarded
    to a vision model).
  - integrations/documents.py's DocumentLoader (checks a file's real content
    matches its extension before extraction).

Magika is loaded lazily so importing this module has no cost until a check
is actually performed.
"""

import functools
import logging

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _magika():
    from magika import Magika
    return Magika()


# Extensions DocumentLoader/the upload endpoint already treat as trusted —
# mapped to the magika label(s) real files of that kind report. This is a
# targeted sanity check against a renamed/mismatched file, not a general
# file-type inventory, so only extensions we actually accept elsewhere are
# listed here.
_ALLOWED_LABELS_BY_EXT = {
    ".pdf":  {"pdf"},
    ".docx": {"docx"},
    ".txt":  {"txt", "empty", "markdown"},
    ".md":   {"markdown", "txt", "empty"},
}

# image/* media types accepted from ImageAttachment, mapped to the magika
# label(s) that content actually is.
_ALLOWED_LABELS_BY_MEDIA_TYPE = {
    "image/png":  {"png"},
    "image/jpeg": {"jpeg"},
    "image/webp": {"webp"},
    "image/gif":  {"gif"},
}


def identify(data: bytes) -> str:
    """Return magika's content-type label for raw bytes (e.g. "pdf", "png")."""
    return _magika().identify_bytes(data).output.label


def verify_extension(data: bytes, suffix: str) -> tuple[bool, str]:
    """
    Check that `data`'s real content matches what a file with extension
    `suffix` (e.g. ".pdf", case-insensitive) is expected to look like.

    Returns (ok, detected_label). Extensions not in _ALLOWED_LABELS_BY_EXT
    have nothing to check against and are reported ok — this stays a
    targeted guard on extensions this codebase already accepts, not a
    general allowlist of every possible file type.
    """
    label = identify(data)
    allowed = _ALLOWED_LABELS_BY_EXT.get(suffix.lower())
    if allowed is None:
        return True, label
    return label in allowed, label


def verify_image(data: bytes, media_type: str) -> tuple[bool, str]:
    """
    Check that `data`'s real content matches a client-declared image
    media_type (e.g. "image/png"). Returns (ok, detected_label). An
    unrecognized/unsupported declared media_type is always rejected.
    """
    label = identify(data)
    allowed = _ALLOWED_LABELS_BY_MEDIA_TYPE.get(media_type.lower())
    if allowed is None:
        return False, label
    return label in allowed, label
