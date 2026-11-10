from app.clock import utcnow
from app.jobs.queue import enqueue_job
from app.models import Job


def test_job_statistics_empty(client) -> None:
    response = client.get("/api/jobs/statistics")
    assert response.status_code == 200
    assert response.json() == {"queued": 0, "running": 0, "finished": 0, "failed": 0}


def test_job_statistics_count_all_jobs(client, app_bundle) -> None:
    _app, services = app_bundle
    with services.session_factory() as session:
        for status, count in (("queued", 3), ("running", 1), ("finished", 205), ("failed", 2)):
            for index in range(count):
                session.add(
                    Job(id=f"{status}-{index}", type="detect", status=status, created_at=utcnow())
                )
        session.commit()

    assert len(client.get("/api/jobs").json()) == 200
    response = client.get("/api/jobs/statistics")
    assert response.status_code == 200
    assert response.json() == {"queued": 3, "running": 1, "finished": 205, "failed": 2}


def test_worker_prioritizes_upload_and_detection_in_queue_order(app_bundle, monkeypatch) -> None:
    app, services = app_bundle
    processed = []

    def record(_session, job, _services) -> None:
        processed.append(job.type)

    monkeypatch.setattr(
        "app.jobs.worker.HANDLERS",
        {job_type: record for job_type in ("retouch", "match", "upload", "detect")},
    )
    session = services.session_factory()
    for job_type in ("retouch", "upload", "match", "detect", "upload"):
        enqueue_job(session, job_type=job_type, payload={})
        session.flush()
    session.commit()
    session.close()

    assert app.state.worker.process_available() == 5
    assert processed == ["upload", "detect", "upload", "retouch", "match"]


def test_worker_runs_a_job_and_records_failure(app_bundle) -> None:
    app, services = app_bundle
    session = services.session_factory()
    job = enqueue_job(session, job_type="detect", scan_id=None, payload={"missing": True})
    session.commit()
    job_id = job.id
    session.close()

    processed = app.state.worker.process_available()
    assert processed == 1
    check = services.session_factory()
    stored = check.get(Job, job_id)
    assert stored is not None
    assert stored.status == "finished"
    assert stored.attempts == 1
    check.close()


def test_handler_exception_marks_the_job_failed(app_bundle) -> None:
    _app, services = app_bundle

    def explode(_session, _job, _services) -> None:
        raise RuntimeError("detector blew up")

    from app.jobs import worker as worker_module

    original = worker_module.HANDLERS["detect"]
    worker_module.HANDLERS["detect"] = explode
    session = services.session_factory()
    job = enqueue_job(session, job_type="detect", payload={})
    session.commit()
    job_id = job.id
    session.close()
    try:
        app_bundle[0].state.worker.process_available()
    finally:
        worker_module.HANDLERS["detect"] = original
    check = services.session_factory()
    stored = check.get(Job, job_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error is not None
    assert "detector blew up" in stored.error
    check.close()


def test_recover_requeues_a_running_job(app_bundle) -> None:
    _app, services = app_bundle
    session = services.session_factory()
    job = Job(
        id="job-running",
        type="detect",
        status="running",
        scan_id=None,
        region_id=None,
        payload="{}",
        error=None,
        attempts=1,
        created_at=utcnow(),
        started_at=utcnow(),
        finished_at=None,
    )
    session.add(job)
    session.commit()
    session.close()
    assert app_bundle[0].state.worker.recover() == 1
    check = services.session_factory()
    stored = check.get(Job, "job-running")
    assert stored is not None
    assert stored.status == "queued"
    assert stored.started_at is None
    check.close()
