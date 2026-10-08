"""Business logic used by the API routes."""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.processor import status_counts
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate
from app.validation import RecipientResult, validate_recipients


class NoValidRecipientsError(Exception):
    def __init__(self, results: list[RecipientResult]):
        self.results = results


def _verification_code() -> str:
    return secrets.token_hex(8).upper()


def create_job(db: Session, payload: JobCreate) -> Job:
    """Validate recipients and persist the job plus one row per recipient in one transaction."""
    results = validate_recipients(payload.recipients)
    if not any(r.is_valid for r in results):
        raise NoValidRecipientsError(results)

    job = Job(
        course_name=payload.course_name,
        issuer=payload.issuer,
        issue_date=payload.issue_date,
        total=len(results),
        status=JobStatus.PENDING,
    )
    for result in results:
        if result.is_valid:
            cert = Certificate(
                row_index=result.row_index,
                recipient_name=result.recipient.name,
                recipient_email=result.recipient.email,
                raw_input=result.raw,
                status=CertificateStatus.PENDING,
                verification_code=_verification_code(),
            )
        else:
            name = result.raw.get("name") if isinstance(result.raw.get("name"), str) else None
            email = result.raw.get("email") if isinstance(result.raw.get("email"), str) else None
            cert = Certificate(
                row_index=result.row_index,
                recipient_name=name[:200] if name else None,
                recipient_email=email[:320] if email else None,
                raw_input=result.raw,
                status=CertificateStatus.INVALID,
                error="; ".join(result.errors),
            )
        job.certificates.append(cert)

    db.add(job)
    db.commit()
    return job


def requeue_unfinished_certificates(db: Session, job: Job) -> int:
    """Move failed certificates back to pending and reopen the job.

    Returns how many certificates will be (re)processed, including any that were left pending
    because the job crashed part-way through.
    """
    failed = db.scalars(
        select(Certificate).where(
            Certificate.job_id == job.id, Certificate.status == CertificateStatus.FAILED
        )
    ).all()
    for cert in failed:
        cert.status = CertificateStatus.PENDING
        cert.error = None
    db.flush()

    to_process = status_counts(db, job.id)[CertificateStatus.PENDING]
    if to_process:
        job.status = JobStatus.PENDING
        job.finished_at = None
    db.commit()
    return to_process


def unfinished_job_ids(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(Job.id).where(Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
        ).all()
    )
