"""
Background jobs for the interface.

Research takes minutes, so the interface starts it on a worker thread and the
page polls for progress. One job runs at a time (a single local user, and one
local model): starting a second returns Busy.

Everything the pipeline prints is captured into the job's log. Cancelling is
cooperative: the next line the pipeline prints raises JobCancelled, so a job
stops at its next step (not mid-way through a single model call).
"""

from __future__ import annotations

import contextlib
import io
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

MAX_LOG_LINES = 3000


class JobCancelled(BaseException):
    """Derives from BaseException so the pipeline's broad `except Exception`
    blocks cannot swallow a cancel."""


class Busy(Exception):
    def __init__(self, job: "Job"):
        super().__init__(f"Another job is running: {job.title}")
        self.job = job


@dataclass
class Job:
    id: str
    kind: str
    title: str
    params: Dict[str, Any]
    status: str = "queued"  # queued | running | done | error | cancelled
    log: List[str] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    dropped_lines: int = 0

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def add(self, line: str) -> None:
        self.log.append(line.rstrip())

        if len(self.log) > MAX_LOG_LINES:
            extra = len(self.log) - MAX_LOG_LINES
            del self.log[:extra]
            self.dropped_lines += extra

    def to_dict(self, since: int = 0, with_log: bool = True) -> Dict[str, Any]:
        """`since` counts lines ever written, so polling survives log trimming."""

        total = self.dropped_lines + len(self.log)
        start = max(0, since - self.dropped_lines)

        data = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1)
            if self.started_at
            else 0,
            "log_total": total,
        }

        if with_log:
            data["log"] = self.log[start:]

        return data


class _LogWriter(io.TextIOBase):
    """Stands in for sys.stdout inside a job thread."""

    def __init__(self, job: Job):
        self.job = job
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self.job.cancel_event.is_set():
            raise JobCancelled()

        self._buffer += text

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.job.add(line)

        return len(text)

    def flush(self) -> None:
        pass

    def finish(self) -> None:
        if self._buffer.strip():
            self.job.add(self._buffer)

        self._buffer = ""


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def active_job(self) -> Optional[Job]:
        with self._lock:
            return next((job for job in self._jobs.values() if job.active), None)

    def start(
        self,
        kind: str,
        title: str,
        params: Dict[str, Any],
        runner: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    ) -> Job:
        with self._lock:
            running = next((job for job in self._jobs.values() if job.active), None)

            if running:
                raise Busy(running)

            job = Job(id=uuid.uuid4().hex[:10], kind=kind, title=title, params=params)
            self._jobs[job.id] = job

            # keep the history short
            for old in sorted(self._jobs.values(), key=lambda j: j.created_at)[:-25]:
                if not old.active:
                    self._jobs.pop(old.id, None)

        threading.Thread(target=self._run, args=(job, runner), daemon=True, name=f"job-{job.id}").start()

        return job

    def _run(self, job: Job, runner) -> None:
        job.status = "running"
        job.started_at = time.time()

        writer = _LogWriter(job)

        try:
            with contextlib.redirect_stdout(writer):
                job.result = runner(job.params) or {}

            job.status = "done"

        except JobCancelled:
            job.status = "cancelled"
            job.add("Stopped.")

        except Exception as exc:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.add(job.error)
            job.add(traceback.format_exc(limit=3).rstrip())

        finally:
            writer.finish()
            job.finished_at = time.time()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 10) -> List[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)

        if job and job.active:
            job.cancel_event.set()
            return True

        return False
