"""
Tests for the magika-based content verification used to guard file uploads
(server.py), image attachments (agents/api_utils.py), and document ingestion
(integrations/documents.py) against mismatched/renamed file content.
"""

from integrations.file_type_check import verify_extension, verify_image

PDF_BYTES = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n"
)
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000a49444154789c6360000002000100"
    "ffff03000006000557bfabd40000000049454e44ae426082"
)
FAKE_PDF_BYTES = b"this is just plain text pretending to be a pdf file" * 5


def test_verify_extension_accepts_real_pdf():
    ok, label = verify_extension(PDF_BYTES, ".pdf")
    assert ok
    assert label == "pdf"


def test_verify_extension_rejects_mismatched_content():
    ok, label = verify_extension(FAKE_PDF_BYTES, ".pdf")
    assert not ok
    assert label != "pdf"


def test_verify_extension_unknown_suffix_is_not_checked():
    ok, _ = verify_extension(PDF_BYTES, ".xyz")
    assert ok


def test_verify_image_accepts_matching_media_type():
    ok, label = verify_image(PNG_BYTES, "image/png")
    assert ok
    assert label == "png"


def test_verify_image_rejects_mismatched_media_type():
    ok, label = verify_image(PNG_BYTES, "image/jpeg")
    assert not ok
    assert label == "png"


def test_verify_image_rejects_unsupported_media_type():
    ok, _ = verify_image(PNG_BYTES, "image/svg+xml")
    assert not ok
