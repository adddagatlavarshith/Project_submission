"""The single, predefined certificate template, rendered as a PDF with ReportLab."""

import io
from dataclasses import dataclass
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
NAVY = colors.HexColor("#1f2a44")
GOLD = colors.HexColor("#b8860b")


@dataclass(frozen=True)
class CertificateData:
    recipient_name: str
    course_name: str
    issuer: str
    issue_date: date
    verification_code: str


def _fit_font_size(text: str, font: str, max_size: int, max_width: float, min_size: int = 14) -> int:
    """Shrink the font until the text fits the available width (long names, long course titles)."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _centered(c: canvas.Canvas, text: str, y: float, font: str, size: int, color=NAVY) -> None:
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawCentredString(PAGE_WIDTH / 2, y, text)


def render_certificate(data: CertificateData) -> bytes:
    """Render one certificate and return the PDF bytes."""
    if not data.recipient_name.strip():
        raise ValueError("recipient name is empty")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"Certificate - {data.recipient_name}")
    c.setAuthor(data.issuer)

    # Double border
    c.setStrokeColor(NAVY)
    c.setLineWidth(4)
    c.rect(24, 24, PAGE_WIDTH - 48, PAGE_HEIGHT - 48)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.rect(36, 36, PAGE_WIDTH - 72, PAGE_HEIGHT - 72)

    text_width = PAGE_WIDTH - 160

    _centered(c, "CERTIFICATE OF COMPLETION", PAGE_HEIGHT - 120, "Helvetica-Bold", 34)
    _centered(c, "This is to certify that", PAGE_HEIGHT - 185, "Helvetica", 16, colors.black)

    name_size = _fit_font_size(data.recipient_name, "Times-BoldItalic", 40, text_width)
    _centered(c, data.recipient_name, PAGE_HEIGHT - 245, "Times-BoldItalic", name_size, GOLD)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(PAGE_WIDTH / 2 - 220, PAGE_HEIGHT - 258, PAGE_WIDTH / 2 + 220, PAGE_HEIGHT - 258)

    _centered(c, "has successfully completed", PAGE_HEIGHT - 295, "Helvetica", 16, colors.black)
    course_size = _fit_font_size(data.course_name, "Helvetica-Bold", 26, text_width)
    _centered(c, data.course_name, PAGE_HEIGHT - 335, "Helvetica-Bold", course_size)

    # Footer: date on the left, issuer on the right, verification code centered.
    footer_y = 120
    c.setFont("Helvetica", 13)
    c.setFillColor(colors.black)
    c.drawCentredString(PAGE_WIDTH * 0.25, footer_y, data.issue_date.strftime("%B %d, %Y"))
    c.drawCentredString(PAGE_WIDTH * 0.75, footer_y, data.issuer)
    c.setStrokeColor(NAVY)
    for x in (PAGE_WIDTH * 0.25, PAGE_WIDTH * 0.75):
        c.line(x - 110, footer_y + 18, x + 110, footer_y + 18)
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(PAGE_WIDTH * 0.25, footer_y - 18, "Date")
    c.drawCentredString(PAGE_WIDTH * 0.75, footer_y - 18, "Issued by")

    _centered(c, f"Verification code: {data.verification_code}", 60, "Courier", 10, colors.grey)

    c.showPage()
    c.save()
    return buffer.getvalue()
