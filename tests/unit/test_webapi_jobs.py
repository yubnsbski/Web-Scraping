"""Tests for async background jobs and the webapi job endpoints."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from investment_assistant.webapi import service
from investment_assistant.webapi.jobs import JobStore, JsonDict


def _wait(store: JobStore, job_id: str, timeout: float = 5.0) -> JsonDict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get(job_id)
        if job is not None and job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish in time")


def test_jobstore_runs_and_returns_result() -> None:
    store = JobStore()
    job_id = store.start("test", lambda: {"value": 42})
    job = _wait(store, job_id)
    assert job["status"] == "done"
    assert job["result"] == {"value": 42}
    assert job["error"] is None
    assert job["finished_at"]
    assert isinstance(job["elapsed_seconds"], int | float)
    assert isinstance(job["duration_seconds"], int | float)
    assert job["elapsed_seconds"] >= 0
    assert job["duration_seconds"] >= 0


def test_jobstore_captures_errors() -> None:
    store = JobStore()

    def boom() -> JsonDict:
        raise RuntimeError("kaboom")

    job: Callable[[], JsonDict] = boom
    job_id = store.start("test", job)
    finished = _wait(store, job_id)
    assert finished["status"] == "error"
    assert "kaboom" in str(finished["error"])
    assert finished["result"] is None
    assert isinstance(finished["duration_seconds"], int | float)


def test_jobstore_reports_running_elapsed_seconds() -> None:
    store = JobStore()
    release = threading.Event()

    def wait_for_release() -> JsonDict:
        release.wait(timeout=5.0)
        return {"released": True}

    job_id = store.start("slow-test", wait_for_release)
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == "running"
    assert isinstance(job["elapsed_seconds"], int | float)
    assert job["elapsed_seconds"] >= 0
    assert job["duration_seconds"] is None

    release.set()
    finished = _wait(store, job_id)
    assert finished["status"] == "done"
    assert isinstance(finished["duration_seconds"], int | float)


def test_jobstore_get_unknown_returns_none() -> None:
    assert JobStore().get("does-not-exist") is None


def test_edinet_ingest_async_runs_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid network: the background job runs a fast stub instead of real ingest.
    monkeypatch.setattr(
        service,
        "_edinet_ingest",
        lambda body: {"ingested_count": 1, "days": body.get("days")},
    )

    status, started = service.handle_api("POST", "/api/edinet/ingest-async", {"days": 7})
    assert status == 200
    assert started["status"] == "running"
    job_id = str(started["job_id"])

    deadline = time.time() + 5.0
    job: JsonDict = {}
    while time.time() < deadline:
        _, job = service.handle_api("POST", "/api/jobs/status", {"job_id": job_id})
        if job.get("status") != "running":
            break
        time.sleep(0.01)

    assert job["status"] == "done"
    assert job["result"] == {"ingested_count": 1, "days": 7}


def test_job_status_unknown_id_is_error() -> None:
    status, payload = service.handle_api("POST", "/api/jobs/status", {"job_id": "missing"})
    assert status == 400
    assert "unknown job_id" in str(payload["error"])
