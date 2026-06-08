"""In-process background jobs for long-running webapi operations.

Long operations (e.g. a multi-minute EDINET ingest over ~220 tickers) exceed the
request timeout of the editor/port-forward proxy in front of the dev server,
surfacing as an HTTP 504 even though the backend finishes. To avoid that, the
handler starts a job, returns a ``job_id`` immediately, and the frontend polls
for completion.

State is in-memory (single-process ThreadingHTTPServer, single-user dashboard);
jobs are lost on restart, which is acceptable for this local tool.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

JsonDict = dict[str, object]


class JobStore:
    """Thread-safe registry of background jobs and their results."""

    def __init__(self) -> None:
        self._jobs: dict[str, JsonDict] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[], JsonDict]) -> str:
        """Run ``fn`` on a daemon thread and return a job id to poll."""

        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "kind": kind,
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "result": None,
                "error": None,
            }
        threading.Thread(target=self._run, args=(job_id, fn), daemon=True).start()
        return job_id

    def get(self, job_id: str) -> JsonDict | None:
        """Return a copy of the job record, or ``None`` if unknown."""

        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def _run(self, job_id: str, fn: Callable[[], JsonDict]) -> None:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - report any failure to the poller
            self._finish(job_id, status="error", error=str(exc))
        else:
            self._finish(job_id, status="done", result=result)

    def _finish(
        self,
        job_id: str,
        *,
        status: str,
        result: JsonDict | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = status
            job["result"] = result
            job["error"] = error
            job["finished_at"] = datetime.now(UTC).isoformat()


# Process-wide store shared across request threads.
JOBS = JobStore()
