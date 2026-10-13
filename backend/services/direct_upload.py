from __future__ import annotations

import json
import logging
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.ingestion import ALLOWED_EXTENSIONS, IngestionError, max_upload_bytes, validate_upload_name
from backend.services.storage import S3Storage, StorageError, storage

_LOGGER = logging.getLogger(__name__)
_UPLOAD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_MIME_TYPES: dict[str, set[str]] = {
    ".avi": {"video/x-msvideo", "video/avi"},
    ".m4v": {"video/x-m4v", "video/mp4"},
    ".mkv": {"video/x-matroska"},
    ".mov": {"video/quicktime"},
    ".mp4": {"video/mp4"},
    ".webm": {"video/webm"},
}
_MIN_PART_SIZE_BYTES = 5 * 1024 * 1024
_MAX_PART_SIZE_BYTES = 5 * 1024 * 1024 * 1024
_MAX_MULTIPART_PARTS = 10_000
_DEFAULT_MULTIPART_THRESHOLD_BYTES = 100 * 1024 * 1024
_DEFAULT_PART_SIZE_BYTES = 64 * 1024 * 1024
_DEFAULT_URL_TTL_SECONDS = 300
_DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60


class UploadServiceError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _r2() -> S3Storage:
    if not isinstance(storage, S3Storage):
        raise UploadServiceError(503, "Direct uploads require STORAGE_BACKEND=r2.")
    return storage


def _max_upload_bytes() -> int:
    try:
        return max_upload_bytes()
    except IngestionError as exc:
        raise UploadServiceError(500, str(exc)) from exc


def _environment_integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise UploadServiceError(500, f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise UploadServiceError(500, f"{name} must be between {minimum} and {maximum}.")
    return value


def upload_configuration() -> dict[str, Any]:
    _r2()
    maximum = _max_upload_bytes()
    _session_ttl()
    part_size = _environment_integer(
        "R2_MULTIPART_PART_SIZE_BYTES",
        _DEFAULT_PART_SIZE_BYTES,
        minimum=_MIN_PART_SIZE_BYTES,
        maximum=_MAX_PART_SIZE_BYTES,
    )
    if math.ceil(maximum / part_size) > _MAX_MULTIPART_PARTS:
        raise UploadServiceError(
            500,
            "MAX_UPLOAD_BYTES exceeds the configured multipart part capacity; increase R2_MULTIPART_PART_SIZE_BYTES.",
        )
    return {
        "max_upload_bytes": maximum,
        "multipart_threshold_bytes": _environment_integer(
            "R2_MULTIPART_THRESHOLD_BYTES",
            _DEFAULT_MULTIPART_THRESHOLD_BYTES,
            minimum=1,
            maximum=5 * 1024 * 1024 * 1024,
        ),
        "part_size_bytes": part_size,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "direct_upload": True,
    }


def local_upload_configuration() -> dict[str, Any]:
    return {
        "max_upload_bytes": max_upload_bytes(),
        "multipart_threshold_bytes": _DEFAULT_MULTIPART_THRESHOLD_BYTES,
        "part_size_bytes": _DEFAULT_PART_SIZE_BYTES,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "direct_upload": False,
    }


def _url_ttl() -> int:
    return _environment_integer("R2_UPLOAD_URL_TTL_SECONDS", _DEFAULT_URL_TTL_SECONDS, minimum=60, maximum=3600)


def _session_ttl() -> int:
    value = _environment_integer(
        "R2_UPLOAD_SESSION_TTL_SECONDS",
        _DEFAULT_SESSION_TTL_SECONDS,
        minimum=600,
        maximum=7 * 24 * 60 * 60,
    )
    if value <= _url_ttl() + 60:
        raise UploadServiceError(
            500,
            "R2_UPLOAD_SESSION_TTL_SECONDS must exceed R2_UPLOAD_URL_TTL_SECONDS by at least 60 seconds.",
        )
    return value


def _session_key(upload_id: str) -> str:
    if not _UPLOAD_ID_PATTERN.fullmatch(upload_id):
        raise UploadServiceError(404, "Upload session not found.")
    return f"uploads/sessions/{upload_id}.json"


def _save_session(session: dict[str, Any]) -> None:
    try:
        storage.put_bytes(
            _session_key(str(session["upload_id"])),
            json.dumps(session, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to save the upload session in object storage.") from exc


def _load_session(upload_id: str, owner_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(storage.get_bytes(_session_key(upload_id)).decode("utf-8"))
    except (OSError, StorageError, UnicodeDecodeError, ValueError, KeyError) as exc:
        raise UploadServiceError(404, "Upload session not found.") from exc
    if not isinstance(payload, dict) or payload.get("owner_id") != owner_id:
        raise UploadServiceError(404, "Upload session not found.")
    if payload.get("status") == "canceled":
        raise UploadServiceError(410, "Upload session was canceled.")
    if payload.get("status") != "completed" and _is_expired(payload):
        _expire_session(payload)
        raise UploadServiceError(410, "Upload session expired. Start the upload again.")
    return payload


def _is_expired(session: dict[str, Any]) -> bool:
    expires_at = session.get("expires_at")
    if not isinstance(expires_at, str):
        return True
    try:
        return datetime.fromisoformat(expires_at).astimezone(timezone.utc) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def _project_owns_uploaded_object(session: dict[str, Any]) -> bool:
    from backend.services.project_service import load_project_metadata

    try:
        metadata = load_project_metadata(str(session.get("video_id"))) or {}
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to verify the uploaded project's storage reference.") from exc
    return (
        metadata.get("owner_id") == session.get("owner_id")
        and metadata.get("source_storage_key") == session.get("object_key")
    )


def _expire_session(session: dict[str, Any]) -> None:
    if session.get("status") == "completed" or (
        session.get("status") == "uploaded" and _project_owns_uploaded_object(session)
    ):
        try:
            storage.delete(_session_key(str(session["upload_id"])))
        except (StorageError, KeyError) as exc:
            raise UploadServiceError(503, "Unable to remove the expired upload session.") from exc
        return
    _discard_session(session)


def _discard_session(session: dict[str, Any], *, keep_tombstone: bool = False) -> None:
    backend = _r2()
    key = session.get("object_key")
    upload_id = session.get("multipart_upload_id")
    try:
        if session.get("status") != "completed":
            if isinstance(upload_id, str):
                backend.abort_multipart_upload(str(key), upload_id)
            if isinstance(key, str):
                backend.delete(key)
        if keep_tombstone:
            session["status"] = "canceled"
            _save_session(session)
        else:
            backend.delete(_session_key(str(session["upload_id"])))
    except (StorageError, KeyError) as exc:
        raise UploadServiceError(503, "Unable to clean up the abandoned upload in R2.") from exc


def cleanup_expired_uploads() -> int:
    backend = _r2()
    try:
        keys = list(backend.list_keys("uploads/sessions/"))
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to check expired upload sessions.") from exc
    cleaned = 0
    for key in keys:
        try:
            payload = json.loads(backend.get_bytes(key).decode("utf-8"))
        except (OSError, StorageError, UnicodeDecodeError, ValueError):
            _LOGGER.warning("Ignoring unreadable upload session %s during cleanup", key)
            continue
        if isinstance(payload, dict) and payload.get("status") != "completed" and _is_expired(payload):
            _expire_session(payload)
            cleaned += 1
        elif isinstance(payload, dict) and payload.get("status") == "completed" and _is_expired(payload):
            try:
                backend.delete(key)
            except StorageError as exc:
                raise UploadServiceError(503, "Unable to remove an expired completed upload session.") from exc
            cleaned += 1
    return cleaned


def start_upload(filename: str, size_bytes: int, content_type: str, owner_id: str) -> dict[str, Any]:
    backend = _r2()
    cleanup_expired_uploads()
    try:
        safe_name = validate_upload_name(filename)
    except IngestionError as exc:
        raise UploadServiceError(400, str(exc)) from exc
    limit = _max_upload_bytes()
    if size_bytes <= 0:
        raise UploadServiceError(400, "The uploaded file is empty.")
    if size_bytes > limit:
        raise UploadServiceError(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
    normalized_type = content_type.strip().lower()
    extension = "." + safe_name.rsplit(".", 1)[-1].lower()
    if normalized_type != "application/octet-stream" and normalized_type not in _MIME_TYPES[extension]:
        raise UploadServiceError(400, "The file content type does not match a supported video format.")

    configuration = upload_configuration()
    session_ttl = _session_ttl()
    upload_id = uuid.uuid4().hex
    video_id = f"upload-{uuid.uuid4().hex}"
    object_key = f"uploads/pending/{upload_id}/{safe_name}"
    use_multipart = size_bytes >= configuration["multipart_threshold_bytes"]
    multipart_upload_id: str | None = None
    try:
        if use_multipart:
            multipart_upload_id = backend.create_multipart_upload(object_key, normalized_type)
        else:
            upload_url = backend.presign_put(object_key, normalized_type, _url_ttl())
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to authorize an R2 upload. Check bucket permissions.") from exc

    session = {
        "upload_id": upload_id,
        "video_id": video_id,
        "owner_id": owner_id,
        "object_key": object_key,
        "filename": safe_name,
        "size_bytes": size_bytes,
        "content_type": normalized_type,
        "upload_mode": "multipart" if use_multipart else "put",
        "part_size_bytes": configuration["part_size_bytes"],
        "multipart_upload_id": multipart_upload_id,
        "status": "pending",
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=session_ttl)).isoformat(),
    }
    try:
        _save_session(session)
    except UploadServiceError:
        if multipart_upload_id:
            try:
                backend.abort_multipart_upload(object_key, multipart_upload_id)
            except StorageError:
                _LOGGER.exception("Unable to abort multipart upload after session persistence failed.")
        raise

    result = {
        "upload_id": upload_id,
        "video_id": video_id,
        "upload_mode": session["upload_mode"],
        "part_size_bytes": session["part_size_bytes"],
        "upload_url": None,
    }
    if not use_multipart:
        result["upload_url"] = upload_url
    return result


def single_upload_url(upload_id: str, owner_id: str) -> str:
    backend = _r2()
    session = _load_session(upload_id, owner_id)
    if session.get("upload_mode") != "put" or session.get("status") != "pending":
        raise UploadServiceError(409, "This upload does not accept a direct PUT.")
    try:
        return backend.presign_put(session["object_key"], session["content_type"], _url_ttl())
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to refresh the upload URL. Check bucket permissions.") from exc


def part_upload_url(upload_id: str, owner_id: str, part_number: int) -> str:
    backend = _r2()
    session = _load_session(upload_id, owner_id)
    if session.get("upload_mode") != "multipart" or session.get("status") != "pending":
        raise UploadServiceError(409, "This upload does not accept multipart parts.")
    total_parts = math.ceil(session["size_bytes"] / session["part_size_bytes"])
    if part_number < 1 or part_number > total_parts or total_parts > _MAX_MULTIPART_PARTS:
        raise UploadServiceError(400, "Invalid multipart part number.")
    try:
        return backend.presign_upload_part(
            session["object_key"], session["multipart_upload_id"], part_number, _url_ttl()
        )
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to refresh the part URL. Check bucket permissions.") from exc


def complete_upload(upload_id: str, owner_id: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.services.analysis_service import start_stored_upload_analysis

    backend = _r2()
    session = _load_session(upload_id, owner_id)
    if session.get("status") == "completed":
        return session["analysis_response"]

    if session.get("status") == "pending" and session["upload_mode"] == "multipart":
        expected_count = math.ceil(session["size_bytes"] / session["part_size_bytes"])
        if expected_count > _MAX_MULTIPART_PARTS or len(parts) != expected_count:
            raise UploadServiceError(400, "The multipart upload is missing one or more parts.")
        normalized_parts = sorted(parts, key=lambda part: part["part_number"])
        if [part["part_number"] for part in normalized_parts] != list(range(1, expected_count + 1)):
            raise UploadServiceError(400, "Multipart part numbers must be complete and sequential.")
        if any("\r" in part["etag"] or "\n" in part["etag"] for part in normalized_parts):
            raise UploadServiceError(400, "Invalid multipart ETag.")
        try:
            if not backend.exists(session["object_key"]):
                backend.complete_multipart_upload(
                    session["object_key"],
                    session["multipart_upload_id"],
                    [{"PartNumber": part["part_number"], "ETag": part["etag"]} for part in normalized_parts],
                )
        except StorageError as exc:
            raise UploadServiceError(503, "R2 could not complete the multipart upload. Retry completion.") from exc
    elif session.get("status") == "pending" and parts:
        raise UploadServiceError(400, "A single-part upload must not include multipart parts.")

    try:
        if not backend.exists(session["object_key"]):
            raise UploadServiceError(409, "The uploaded object is not present in R2 yet.")
        metadata = backend.object_metadata(session["object_key"])
    except StorageError as exc:
        raise UploadServiceError(503, "Unable to verify the uploaded R2 object.") from exc
    if metadata.get("size") != session["size_bytes"]:
        _discard_session(session)
        raise UploadServiceError(400, "The uploaded object size does not match the authorized file size.")
    stored_type = str(metadata.get("content_type") or "").lower()
    if stored_type != session["content_type"]:
        _discard_session(session)
        raise UploadServiceError(400, "The uploaded object's content type does not match the authorized type.")

    session["status"] = "uploaded"
    _save_session(session)
    try:
        response = start_stored_upload_analysis(
            session["video_id"],
            session["object_key"],
            filename=session["filename"],
            owner_id=owner_id,
            size_bytes=session["size_bytes"],
        )
    except (ValueError, RuntimeError, StorageError) as exc:
        raise UploadServiceError(409, str(exc)) from exc
    session["status"] = "completed"
    session["analysis_response"] = response.model_dump(mode="json")
    _save_session(session)
    return session["analysis_response"]


def cancel_upload(upload_id: str, owner_id: str) -> None:
    session = _load_session(upload_id, owner_id)
    if session.get("status") in {"uploaded", "completed"}:
        raise UploadServiceError(409, "Processing has started; this upload can no longer be canceled.")
    _discard_session(session, keep_tombstone=True)
