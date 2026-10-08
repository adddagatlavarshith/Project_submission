import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services, storage, worker
from app.config import get_settings
from app.database import get_db
from app.models import Certificate, CertificateStatus, Job
from app.processor import FINAL_JOB_STATUSES, status_counts
from app.schemas import CertificateOut, CertificatePage, JobCreate, JobOut, StatusCounts

router = APIRouter(prefix="/api/v1")


def _job_out(db: Session, job: Job, request: Request) -> JobOut:
    counts = status_counts(db, job.id)
    done = job.total - counts[CertificateStatus.PENDING]
    return JobOut(
        id=job.id,
        status=job.status,
        course_name=job.course_name,
        issuer=job.issuer,
        issue_date=job.issue_date,
        total=job.total,
        counts=StatusCounts(**{s.value: n for s, n in counts.items()}),
        progress_percent=round(100 * done / job.total, 2) if job.total else 100.0,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        links={
            "self": str(request.url_for("get_job", job_id=job.id)),
            "certificates": str(request.url_for("list_job_certificates", job_id=job.id)),
            "download_zip": str(request.url_for("download_job_zip", job_id=job.id)),
        },
    )


def _certificate_out(cert: Certificate, request: Request) -> CertificateOut:
    download_url = None
    if cert.status == CertificateStatus.GENERATED:
        download_url = str(request.url_for("download_certificate", certificate_id=cert.id))
    return CertificateOut(
        id=cert.id,
        job_id=cert.job_id,
        row_index=cert.row_index,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        status=cert.status,
        error=cert.error,
        verification_code=cert.verification_code,
        generated_at=cert.generated_at,
        download_url=download_url,
    )


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def create_job(payload: JobCreate, request: Request, db: Session = Depends(get_db)):
    """Submit a bulk certificate generation request.

    Returns 202 immediately; generation runs in the background. Poll the job to track progress.
    """
    max_recipients = get_settings().max_recipients
    if len(payload.recipients) > max_recipients:
        raise HTTPException(
            422,
            f"Too many recipients: {len(payload.recipients)} (max {max_recipients})",
        )
    try:
        job = services.create_job(db, payload)
    except services.NoValidRecipientsError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "No valid recipients in request",
                "errors": [{"index": r.row_index, "errors": r.errors} for r in exc.results],
            },
        )

    worker.dispatch(job.id)
    db.refresh(job)
    body = _job_out(db, job, request)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=body.model_dump(mode="json"),
        headers={"Location": body.links["self"]},
    )


@router.get("/jobs/{job_id}", response_model=JobOut, name="get_job")
def get_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Job status with per-state counts and progress."""
    return _job_out(db, _get_job_or_404(db, job_id), request)


@router.get("/jobs/{job_id}/certificates", response_model=CertificatePage, name="list_job_certificates")
def list_job_certificates(
    job_id: str,
    request: Request,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Per-recipient results (paginated), including errors for failed/invalid recipients."""
    _get_job_or_404(db, job_id)
    query = select(Certificate).where(Certificate.job_id == job_id)
    if status_filter is not None:
        query = query.where(Certificate.status == status_filter)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    certs = db.scalars(query.order_by(Certificate.row_index).offset(offset).limit(limit)).all()
    return CertificatePage(
        items=[_certificate_out(c, request) for c in certs], total=total, offset=offset, limit=limit
    )


@router.get("/jobs/{job_id}/download", name="download_job_zip")
def download_job_zip(job_id: str, db: Session = Depends(get_db)):
    """All generated certificates of a job as a ZIP archive."""
    _get_job_or_404(db, job_id)
    certs = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.GENERATED)
        .order_by(Certificate.row_index)
    ).all()
    if not certs:
        raise HTTPException(status.HTTP_409_CONFLICT, "No certificates have been generated yet")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for cert in certs:
            path = storage.resolve(cert.file_path or "")
            if path is not None:
                archive.write(path, arcname=_download_filename(cert))
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job_id}.zip"'},
    )


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Re-run generation for certificates that failed (invalid recipients are not retried)."""
    job = _get_job_or_404(db, job_id)
    if job.status not in FINAL_JOB_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is still running")
    if services.requeue_unfinished_certificates(db, job):
        worker.dispatch(job.id)
        db.refresh(job)
    return _job_out(db, job, request)


@router.get("/certificates/{certificate_id}", response_model=CertificateOut)
def get_certificate(certificate_id: str, request: Request, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    return _certificate_out(cert, request)


@router.get("/certificates/{certificate_id}/download", name="download_certificate")
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    if cert.status != CertificateStatus.GENERATED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Certificate is not available (status: {cert.status.value})"
        )
    path = storage.resolve(cert.file_path or "")
    if path is None:
        raise HTTPException(status.HTTP_410_GONE, "Certificate file is missing from storage")
    return FileResponse(path, media_type="application/pdf", filename=_download_filename(cert))


def _download_filename(cert: Certificate) -> str:
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in (cert.recipient_name or "certificate"))
    return f"{cert.row_index:05d}_{safe_name.strip('_')[:60]}.pdf"
