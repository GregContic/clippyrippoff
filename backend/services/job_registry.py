from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.utils import PROCESSING_TEMP_DIR
from backend.services.storage import S3Storage, storage


JOB_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{32,36}$")


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
    retry_of: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    review_status: str = "pending_review"
    review_notes: str = ""

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
            "retry_of": self.retry_of,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "review_status": self.review_status,
            "review_notes": self.review_notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobRecord":
        return cls(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            status=str(payload.get("status", "queued")),
            video_id=payload.get("video_id"),
            candidate_id=payload.get("candidate_id"),
            stage=payload.get("stage"),
            message=payload.get("message"),
            percent=payload.get("percent"),
            error=payload.get("error"),
            output_path=payload.get("output_path"),
            output_url=payload.get("output_url"),
            result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
            retry_of=payload.get("retry_of"),
            created_at=str(payload.get("created_at", _now())),
            updated_at=str(payload.get("updated_at", _now())),
            review_status=str(payload.get("review_status", "pending_review")),
            review_notes=str(payload.get("review_notes", "")),
        )


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self.storage_dir = PROCESSING_TEMP_DIR / "render_jobs"

    def _job_path(self, job_id: str) -> Path:
        if not JOB_ID_PATTERN.match(job_id):
            raise ValueError(f"Invalid job ID: {job_id}")
        return self.storage_dir / f"{job_id}.json"

    def _write_record(self, record: JobRecord) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        path = self._job_path(record.id)
        payload = record.to_dict()
        tmp_path = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
        if isinstance(storage, S3Storage):
            storage.put_bytes(
                f"jobs/{record.id}.json",
                json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )

    def _delete_record_file(self, job_id: str) -> None:
        path = self._job_path(job_id)
        if path.exists():
            path.unlink()

    def _store(self, record: JobRecord) -> JobRecord:
        with self._lock:
            self._jobs[record.id] = record
            self._write_record(record)
        return record

    def _persist(self, record: JobRecord) -> None:
        with self._lock:
            self._write_record(record)

    def _load_file(self, path: Path) -> JobRecord | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or "id" not in payload or "kind" not in payload:
            return None
        try:
            return JobRecord.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return None

    def restore_from_disk(self) -> None:
        restored: dict[str, JobRecord] = {}
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        for path in self.storage_dir.glob("*.json"):
            record = self._load_file(path)
            if record is None:
                continue
            if record.status in {"queued", "running"}:
                record.status = "interrupted"
                record.stage = "interrupted"
                record.message = "Interrupted by backend restart."
                record.updated_at = _now()
            restored[record.id] = record
        for key in storage.list_keys("jobs/") if isinstance(storage, S3Storage) else ():
            if not key.endswith(".json"):
                continue
            try:
                payload = json.loads(storage.get_bytes(key).decode("utf-8"))
                record = JobRecord.from_dict(payload)
            except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
                continue
            restored[record.id] = record
        with self._lock:
            self._jobs = restored
            for record in restored.values():
                self._write_record(record)

    def create(
        self,
        kind: str,
        *,
        video_id: str | None = None,
        candidate_id: int | None = None,
        stage: str | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        retry_of: str | None = None,
        percent: float | None = None,
    ) -> JobRecord:
        record = JobRecord(
            id=str(uuid.uuid4()),
            kind=kind,
            video_id=video_id,
            candidate_id=candidate_id,
            stage=stage,
            message=message,
            result=result,
            retry_of=retry_of,
            percent=percent,
        )
        return self._store(record)

    def update(self, job_id: str, **changes: Any) -> JobRecord:
        with self._lock:
            record = self._jobs[job_id]
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = _now()
            self._write_record(record)
            return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def remove(self, job_id: str) -> bool:
        with self._lock:
            removed = self._jobs.pop(job_id, None) is not None
            if removed:
                self._delete_record_file(job_id)
            return removed

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
