import io
import zipfile

from app import processor


def test_download_single_certificate(client, create_job):
    job = create_job()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]

    response = client.get(item["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "Ada_Lovelace" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_get_certificate_metadata(client, create_job):
    job = create_job()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][1]

    body = client.get(f"/api/v1/certificates/{item['id']}").json()

    assert body["recipient_name"] == "Alan Turing"
    assert body["recipient_email"] == "alan@example.com"
    assert body["status"] == "generated"


def test_download_unknown_certificate_is_404(client):
    assert client.get("/api/v1/certificates/nope/download").status_code == 404
    assert client.get("/api/v1/certificates/nope").status_code == 404


def test_download_failed_certificate_is_409(client, create_job, monkeypatch):
    def always_fail(data):
        raise RuntimeError("boom")

    monkeypatch.setattr(processor, "render_certificate", always_fail)
    job = create_job()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]

    assert client.get(f"/api/v1/certificates/{item['id']}/download").status_code == 409
    assert client.get(f"/api/v1/jobs/{job['id']}/download").status_code == 409


def test_download_zip_contains_all_generated_certificates(client, create_job, job_payload):
    job_payload["recipients"].append({"name": ""})  # invalid -> excluded from the zip
    job = create_job(job_payload)

    response = client.get(f"/api/v1/jobs/{job['id']}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert names == ["00000_Ada_Lovelace.pdf", "00001_Alan_Turing.pdf", "00002_Grace_Hopper.pdf"]
        assert all(archive.read(n).startswith(b"%PDF") for n in names)


def test_certificate_listing_pagination_and_filter(client, create_job, job_payload):
    job_payload["recipients"] = [{"name": f"Person {i}"} for i in range(7)] + [{"name": ""}]
    job = create_job(job_payload)
    url = f"/api/v1/jobs/{job['id']}/certificates"

    page = client.get(url, params={"offset": 5, "limit": 2}).json()
    assert page["total"] == 8
    assert [i["row_index"] for i in page["items"]] == [5, 6]

    generated = client.get(url, params={"status": "generated"}).json()
    assert generated["total"] == 7

    assert client.get(url, params={"status": "bogus"}).status_code == 422
    assert client.get("/api/v1/jobs/unknown/certificates").status_code == 404


def test_missing_file_on_disk_is_410(client, create_job):
    import os

    job = create_job()
    item = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"][0]
    from app import database
    from app.models import Certificate

    with database.SessionLocal() as db:
        os.remove(db.get(Certificate, item["id"]).file_path)

    assert client.get(item["download_url"]).status_code == 410
