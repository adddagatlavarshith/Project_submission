from app import database
from app.models import Certificate, Job


def test_create_job_returns_202_with_job_id(client, job_payload):
    response = client.post("/api/v1/jobs", json=job_payload)

    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["total"] == 3
    assert body["course_name"] == "Intro to Python"
    assert response.headers["Location"].endswith(f"/api/v1/jobs/{body['id']}")
    assert body["links"]["certificates"].endswith(f"/api/v1/jobs/{body['id']}/certificates")


def test_create_job_persists_one_row_per_recipient(client, create_job):
    body = create_job()

    with database.SessionLocal() as db:
        job = db.get(Job, body["id"])
        assert job is not None
        rows = db.query(Certificate).filter_by(job_id=job.id).order_by(Certificate.row_index).all()
        assert [r.recipient_name for r in rows] == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
        assert [r.row_index for r in rows] == [0, 1, 2]
        assert all(r.verification_code for r in rows)


def test_background_mode_dispatches_without_blocking(client, job_payload, monkeypatch):
    from app import worker
    from app.config import get_settings

    submitted = []
    monkeypatch.setattr(get_settings(), "processing_mode", "background")

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append(args)

    monkeypatch.setattr(worker, "_get_executor", lambda: FakeExecutor())

    response = client.post("/api/v1/jobs", json=job_payload)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["counts"]["pending"] == 3
    assert submitted == [(body["id"],)]
