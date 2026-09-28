from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str = "queued"
    video_id: str | None = None
    candidate_id: int | None = None
    stage: str | None = None
    message: str | None = None
    percent: float | None = None
    error: str | None = None
    output_path: str | None = None
    output_url: str | None = None
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "video_id": self.video_id,
            "candidate_id": self.candidate_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "percent": self.percent,
            "error": self.error,
            "output_path": self.output_path,
            "output_url": self.output_url,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        kind: str,
        *,
        video_id: str | None = None,
        candidate_id: int | None = None,
        stage: str | None = None,
        message: str | None = None,
    ) -> JobRecord:
        record = JobRecord(
            id=str(uuid.uuid4()),
            kind=kind,
            video_id=video_id,
            candidate_id=candidate_id,
            stage=stage,
            message=message,
        )
        with self._lock:
            self._jobs[record.id] = record
        return record

    def update(self, job_id: str, **changes: Any) -> JobRecord:
        with self._lock:
            record = self._jobs[job_id]
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = _now()
            return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def remove(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()

    def submit(self, kind: str, runner: Callable[[str], None], **job_kwargs: Any) -> JobRecord:
        record = self.create(kind, **job_kwargs)

        def _wrapped() -> None:
            try:
                self.update(record.id, status="running", stage=record.stage or kind, message=record.message)
                runner(record.id)
            except Exception as exc:  # pragma: no cover - safety net for background jobs
                self.update(record.id, status="failed", error=str(exc), message="Job failed.")

        thread = threading.Thread(target=_wrapped, daemon=True)
        thread.start()
        return record


job_registry = JobRegistry()
