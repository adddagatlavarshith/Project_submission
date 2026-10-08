from app import generator, processor


def _fail_for(name: str, monkeypatch):
    """Make rendering raise for one specific recipient."""
    real_render = generator.render_certificate

    def flaky_render(data):
        if data.recipient_name == name:
            raise RuntimeError("template rendering exploded")
        return real_render(data)

    monkeypatch.setattr(processor, "render_certificate", flaky_render)


def test_one_failure_does_not_stop_other_certificates(client, create_job, monkeypatch):
    _fail_for("Alan Turing", monkeypatch)

    job = create_job()

    assert job["status"] == "completed_with_errors"
    assert job["counts"] == {"pending": 0, "generated": 2, "failed": 1, "invalid": 0}

    items = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()["items"]
    statuses = {item["recipient_name"]: item for item in items}
    assert statuses["Ada Lovelace"]["status"] == "generated"
    assert statuses["Grace Hopper"]["status"] == "generated"
    failed = statuses["Alan Turing"]
    assert failed["status"] == "failed"
    assert failed["error"] == "RuntimeError: template rendering exploded"
    assert failed["download_url"] is None


def test_job_fails_when_every_certificate_fails(client, create_job, monkeypatch):
    def always_fail(data):
        raise RuntimeError("boom")

    monkeypatch.setattr(processor, "render_certificate", always_fail)

    job = create_job()

    assert job["status"] == "failed"
    assert job["counts"]["failed"] == 3


def test_storage_failure_is_isolated_too(client, create_job, monkeypatch):
    from app import storage

    real_save = storage.save_certificate
    calls = {"n": 0}

    def save_with_one_failure(job_id, cert_id, content):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real_save(job_id, cert_id, content)

    monkeypatch.setattr(storage, "save_certificate", save_with_one_failure)

    job = create_job()
    assert job["counts"]["generated"] == 2
    assert job["counts"]["failed"] == 1


def test_retry_regenerates_only_failed_certificates(client, create_job, monkeypatch):
    with monkeypatch.context() as m:
        _fail_for("Alan Turing", m)
        job = create_job()
    # The transient problem is now fixed.
    url = f"/api/v1/jobs/{job['id']}/certificates"
    before = {i["recipient_name"]: i for i in client.get(url).json()["items"]}
    assert before["Alan Turing"]["status"] == "failed"

    response = client.post(f"/api/v1/jobs/{job['id']}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["counts"]["generated"] == 3
    after = {i["recipient_name"]: i for i in client.get(url).json()["items"]}
    # Already generated certificates are untouched.
    assert after["Ada Lovelace"]["generated_at"] == before["Ada Lovelace"]["generated_at"]
    assert after["Alan Turing"]["status"] == "generated"


def test_retry_is_rejected_while_job_is_running(client, create_job, monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "dispatch", lambda job_id: None)
    job = create_job()  # stays pending

    assert client.post(f"/api/v1/jobs/{job['id']}/retry").status_code == 409
