from app import database, processor
from app.models import Certificate, CertificateStatus, Job, JobStatus


def test_job_status_reports_counts_and_progress(client, create_job):
    job = create_job()

    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["status"] == "completed"
    assert body["counts"] == {"pending": 0, "generated": 3, "failed": 0, "invalid": 0}
    assert body["progress_percent"] == 100.0
    assert body["started_at"] and body["finished_at"]


def test_status_for_unknown_job_is_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404


def test_progress_while_job_is_partially_processed(client, create_job, monkeypatch):
    # Create the job without processing it, then mark one certificate as done by hand.
    from app import worker

    monkeypatch.setattr(worker, "dispatch", lambda job_id: None)
    job = create_job()
    with database.SessionLocal() as db:
        cert = db.query(Certificate).filter_by(job_id=job["id"], row_index=0).one()
        cert.status = CertificateStatus.GENERATED
        db.get(Job, job["id"]).status = JobStatus.PROCESSING
        db.commit()

    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["status"] == "processing"
    assert body["counts"]["pending"] == 2
    assert body["counts"]["generated"] == 1
    assert body["progress_percent"] == 33.33


def test_processing_is_idempotent(client, create_job):
    job = create_job()
    processor.process_job(job["id"])  # already finished -> no-op

    body = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert body["counts"]["generated"] == 3


def test_unfinished_jobs_are_resumed_on_startup(job_payload, monkeypatch):
    from fastapi.testclient import TestClient

    from app import worker
    from app.main import app

    # Submit a job whose processing never happens (simulates a crash before the worker ran).
    with monkeypatch.context() as m:
        m.setattr(worker, "dispatch", lambda job_id: None)
        with TestClient(app) as client:
            job_id = client.post("/api/v1/jobs", json=job_payload).json()["id"]
            assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "pending"

    # Restarting the app picks it up again.
    with TestClient(app) as client:
        assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "completed"
