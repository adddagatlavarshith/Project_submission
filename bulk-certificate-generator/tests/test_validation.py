import pytest

from app.config import get_settings
from app.validation import validate_recipients


@pytest.mark.parametrize("missing", ["course_name", "issuer", "issue_date", "recipients"])
def test_missing_required_job_fields_rejected(client, job_payload, missing):
    del job_payload[missing]
    assert client.post("/api/v1/jobs", json=job_payload).status_code == 422


def test_invalid_issue_date_rejected(client, job_payload):
    job_payload["issue_date"] = "not-a-date"
    assert client.post("/api/v1/jobs", json=job_payload).status_code == 422


def test_blank_course_name_rejected(client, job_payload):
    job_payload["course_name"] = "   "
    assert client.post("/api/v1/jobs", json=job_payload).status_code == 422


def test_empty_recipient_list_rejected(client, job_payload):
    job_payload["recipients"] = []
    assert client.post("/api/v1/jobs", json=job_payload).status_code == 422


def test_too_many_recipients_rejected(client, job_payload, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_recipients", 2)
    response = client.post("/api/v1/jobs", json=job_payload)
    assert response.status_code == 422
    assert "Too many recipients" in response.json()["detail"]


def test_all_recipients_invalid_rejected_with_details(client, job_payload):
    job_payload["recipients"] = [{"name": ""}, {"email": "x@example.com"}, "just a string"]
    response = client.post("/api/v1/jobs", json=job_payload)

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert [e["index"] for e in errors] == [0, 1, 2]
    assert all(e["errors"] for e in errors)


def test_mixed_valid_and_invalid_recipients_accepted(client, create_job, job_payload):
    job_payload["recipients"] = [
        {"name": "Valid Person", "email": "valid@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"name": ""},
        {"name": "Another Valid"},
    ]
    job = create_job(job_payload)

    assert job["total"] == 4
    assert job["counts"]["generated"] == 2
    assert job["counts"]["invalid"] == 2
    assert job["status"] == "completed_with_errors"

    invalid = client.get(f"/api/v1/jobs/{job['id']}/certificates", params={"status": "invalid"}).json()
    by_index = {item["row_index"]: item for item in invalid["items"]}
    assert set(by_index) == {1, 2}
    assert "email" in by_index[1]["error"]
    assert by_index[1]["recipient_name"] == "Bad Email"
    assert "name" in by_index[2]["error"]
    assert all(item["download_url"] is None for item in invalid["items"])


def test_validate_recipients_rules():
    results = validate_recipients(
        [
            {"name": "  Ada  ", "email": "ADA@example.com"},
            {"name": "Ada Again", "email": "ada@example.com"},  # duplicate email (case-insensitive)
            {"name": "x" * 101},  # too long
            {"name": "Bad\x00Name"},  # control character
            {"name": "Extra", "unknown": "field"},  # unknown field
            42,  # not an object
        ]
    )

    assert results[0].is_valid and results[0].recipient.name == "Ada"
    assert not results[1].is_valid and "duplicate" in results[1].errors[0]
    assert not results[2].is_valid
    assert not results[3].is_valid and "control characters" in results[3].errors[0]
    assert not results[4].is_valid
    assert not results[5].is_valid and results[5].errors == ["recipient must be an object"]
