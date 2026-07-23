from app.rag.text_extraction import extract_pdf_text
from tests.pdf_fixtures import make_image_only_pdf, make_text_layer_pdf


def test_extract_pdf_text_returns_text_for_text_layer_pdf():
    pdf_bytes = make_text_layer_pdf("Patient reports mild headache, no fever.")
    result = extract_pdf_text(pdf_bytes)
    assert "headache" in result.lower()


def test_extract_pdf_text_returns_empty_for_image_only_pdf():
    pdf_bytes = make_image_only_pdf()
    result = extract_pdf_text(pdf_bytes)
    assert result == ""


def test_extract_pdf_text_strips_and_collapses_whitespace():
    pdf_bytes = make_text_layer_pdf("Line one.")
    result = extract_pdf_text(pdf_bytes)
    assert result == result.strip()
    assert "  " not in result
