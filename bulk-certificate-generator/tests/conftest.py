import os

import pytest

# Configure before the app modules are imported.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["PROCESSING_MODE"] = "sync"  # run jobs inline so tests are deterministic

from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Fresh SQLite database and storage directory for every test."""
    database.configure_database(f"sqlite:///{tmp_path / 'test.db'}")
    database.init_db()
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "processing_mode", "sync")
    yield
    database.engine.dispose()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def job_payload():
    return {
        "course_name": "Intro to Python",
        "issuer": "Acme Academy",
        "issue_date": "2026-10-01",
        "recipients": [
            {"name": "Ada Lovelace", "email": "ada@example.com"},
            {"name": "Alan Turing", "email": "alan@example.com"},
            {"name": "Grace Hopper"},
        ],
    }


@pytest.fixture
def create_job(client, job_payload):
    def _create(payload=None):
        response = client.post("/api/v1/jobs", json=payload or job_payload)
        assert response.status_code == 202, response.text
        return response.json()

    return _create
