from io import BytesIO

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def make_text_layer_pdf(
    text: str = "Patient consultation note: blood pressure 120 over 80, no acute distress.",
) -> bytes:
    """A real PDF with an actual extractable text layer (born-digital)."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return buffer.getvalue()


def make_image_only_pdf() -> bytes:
    """A real PDF with a rendered raster image and zero text operators.

    Simulates a scanned/image-only document: pypdf's extract_text() returns
    empty for this, same as it would for a real scan with no OCR text layer.
    """
    image = Image.new("RGB", (200, 200), color=(120, 120, 200))
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer)
    c.drawImage(ImageReader(image_buffer), 72, 500, width=200, height=200)
    c.showPage()
    c.save()
    return pdf_buffer.getvalue()