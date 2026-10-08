import io
from datetime import date

import pytest
from pypdf import PdfReader

from app.generator import CertificateData, render_certificate


def _text(pdf: bytes) -> str:
    return PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


def _data(**overrides) -> CertificateData:
    values = dict(
        recipient_name="Ada Lovelace",
        course_name="Intro to Python",
        issuer="Acme Academy",
        issue_date=date(2026, 10, 1),
        verification_code="ABC123",
    )
    values.update(overrides)
    return CertificateData(**values)


def test_render_certificate_produces_pdf_with_recipient_details():
    pdf = render_certificate(_data())

    assert pdf.startswith(b"%PDF")
    text = _text(pdf)
    for expected in ["Ada Lovelace", "Intro to Python", "Acme Academy", "October 01, 2026", "ABC123"]:
        assert expected in text


def test_render_certificate_handles_long_names():
    long_name = "Maria Anna Sophia Cecilia Kalogeropoulou-Vandersteen Montgomery III"
    assert long_name in _text(render_certificate(_data(recipient_name=long_name)))


def test_render_certificate_rejects_empty_name():
    with pytest.raises(ValueError):
        render_certificate(_data(recipient_name="  "))


def test_job_generates_a_pdf_file_per_recipient(client, create_job):
    job = create_job()

    assert job["status"] == "completed"
    assert job["counts"]["generated"] == 3

    items = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"]
    for item in items:
        pdf = client.get(item["download_url"]).content
        assert item["recipient_name"] in _text(pdf)
        assert item["verification_code"] in _text(pdf)
