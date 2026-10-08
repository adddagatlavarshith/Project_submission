"""Job processing: turns pending certificate rows into PDF files.

Every certificate is generated inside its own try/except, so one failure is recorded on that
certificate only and the rest of the job continues.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.database import SessionLocal
from app.generator import CertificateData, render_certificate
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow

logger = logging.getLogger(__name__)

FINAL_JOB_STATUSES = {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED}


def status_counts(db: Session, job_id: str) -> dict[CertificateStatus, int]:
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    counts = {status: 0 for status in CertificateStatus}
    counts.update({status: count for status, count in rows})
    return counts


def _final_status(counts: dict[CertificateStatus, int]) -> JobStatus:
    if counts[CertificateStatus.GENERATED] == 0:
        return JobStatus.FAILED
    if counts[CertificateStatus.FAILED] or counts[CertificateStatus.INVALID]:
        return JobStatus.COMPLETED_WITH_ERRORS
    return JobStatus.COMPLETED


def generate_one(job: Job, cert: Certificate) -> None:
    """Generate and store a single certificate, updating the row in place."""
    data = CertificateData(
        recipient_name=cert.recipient_name or "",
        course_name=job.course_name,
        issuer=job.issuer,
        issue_date=job.issue_date,
        verification_code=cert.verification_code or "",
    )
    pdf = render_certificate(data)
    cert.file_path = storage.save_certificate(job.id, cert.id, pdf)
    cert.status = CertificateStatus.GENERATED
    cert.error = None
    cert.generated_at = utcnow()


def process_job(job_id: str) -> None:
    batch_size = get_settings().commit_batch_size
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status in FINAL_JOB_STATUSES:
            return

        job.status = JobStatus.PROCESSING
        job.started_at = job.started_at or utcnow()
        db.commit()

        while True:
            batch = db.scalars(
                select(Certificate)
                .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING)
                .order_by(Certificate.row_index)
                .limit(batch_size)
            ).all()
            if not batch:
                break

            for cert in batch:
                try:
                    generate_one(job, cert)
                except Exception as exc:  # isolate the failure to this certificate
                    logger.exception("Certificate %s in job %s failed", cert.id, job_id)
                    cert.status = CertificateStatus.FAILED
                    cert.error = f"{type(exc).__name__}: {exc}"
            # Commit per batch so clients polling the job see progress.
            db.commit()

        job.status = _final_status(status_counts(db, job_id))
        job.finished_at = utcnow()
        db.commit()
        logger.info("Job %s finished with status %s", job_id, job.status.value)
    except Exception:
        # Something outside a single certificate broke (e.g. the database). Mark the job as
        # failed so it does not look stuck; certificates left pending can be retried.
        logger.exception("Job %s crashed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.finished_at = utcnow()
            db.commit()
    finally:
        db.close()
