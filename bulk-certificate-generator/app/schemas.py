from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import CertificateStatus, JobStatus


def _no_control_chars(value: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("must not contain control characters")
    return value


class RecipientIn(BaseModel):
    """Schema for a single recipient. Validated per recipient, not per request (see validation.py)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = None

    _check_name = field_validator("name")(_no_control_chars)


class JobCreate(BaseModel):
    """Request body for a bulk generation job.

    `recipients` is intentionally typed loosely (a list of arbitrary objects): a bad recipient
    should not reject the whole request. Each entry is validated individually against
    `RecipientIn`, and failures are reported per recipient in the job results.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    course_name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(min_length=1, max_length=200)
    issue_date: date
    recipients: list[Any] = Field(min_length=1)

    _check_text = field_validator("course_name", "issuer")(_no_control_chars)


class StatusCounts(BaseModel):
    pending: int = 0
    generated: int = 0
    failed: int = 0
    invalid: int = 0


class JobOut(BaseModel):
    id: str
    status: JobStatus
    course_name: str
    issuer: str
    issue_date: date
    total: int
    counts: StatusCounts
    progress_percent: float = Field(description="Share of recipients that reached a final state")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    links: dict[str, str]


class CertificateOut(BaseModel):
    id: str
    job_id: str
    row_index: int
    recipient_name: str | None
    recipient_email: str | None
    status: CertificateStatus
    error: str | None
    verification_code: str | None
    generated_at: datetime | None
    download_url: str | None


class CertificatePage(BaseModel):
    items: list[CertificateOut]
    total: int
    offset: int
    limit: int
