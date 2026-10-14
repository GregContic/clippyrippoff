from __future__ import annotations

import logging
import mimetypes
import shutil
import threading
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Any, Callable

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.schemas import AnalyzeResponse
from backend.services.job_registry import job_registry
from backend.services.project_service import (
    find_project_by_url,
    load_project_metadata,
    patch_project_metadata,
    project_summary,
    save_candidates,
    save_project_metadata,
    youtube_project_id,
)
from scripts.detect_clips import detect_candidates
from scripts.youtube import (
    BOT_CHALLENGE_MESSAGE,
    YouTubeBotChallengeError,
    YouTubeError,
    YouTubeNetworkError,
    YouTubeRateLimitError,
    YouTubeUnavailableError,
    cache_paths,
    download_youtube_video,
    extract_video_id,
)
from scripts.utils import FFmpegNotFoundError, PROCESSING_TEMP_DIR, TranscriptionError, get_media_info, load_config
from backend.services.storage import storage
from backend.services.storage import StorageError
from backend.services.ingestion import YouTubeProvider
from backend.services.media_concurrency import run_media_task

_LOGGER = logging.getLogger(__name__)
_ANALYSIS_START_LOCK = threading.Lock()
_YOUTUBE_SOURCE_CACHE_DIR = PROCESSING_TEMP_DIR / "youtube_sources"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _active_cooldown_error(metadata: dict[str, Any]) -> YouTubeError | None:
    retry_after_raw = metadata.get("retry_after")
    failure_code = metadata.get("failure_code")
    if not isinstance(retry_after_raw, str) or failure_code not in {
        YouTubeRateLimitError.failure_code,
        YouTubeBotChallengeError.failure_code,
    }:
        return None
    try:
        retry_after = datetime.fromisoformat(retry_after_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if retry_after.tzinfo is None:
        retry_after = retry_after.replace(tzinfo=timezone.utc)
    remaining = ceil((retry_after - _utcnow()).total_seconds())
    if remaining <= 0:
        return None
    if failure_code == YouTubeBotChallengeError.failure_code:
        return YouTubeBotChallengeError(
            f"{BOT_CHALLENGE_MESSAGE} Retry after {retry_after.isoformat()}.",
            retry_after_seconds=remaining,
        )
    return YouTubeRateLimitError(
        f"YouTube is rate-limiting this source. Retry after {retry_after.isoformat()} "
        "or upload the video directly.",
        retry_after_seconds=remaining,
    )


def _failure_metadata(exc: Exception, message: str) -> dict[str, Any]:
    failure_code = getattr(exc, "failure_code", type(exc).__name__)
    result: dict[str, Any] = {
        "failure_code": failure_code,
        "retry_after": None,
        "retry_after_seconds": None,
        "message": message,
    }
    retry_after_seconds = getattr(exc, "retry_after_seconds", None)
    if not isinstance(retry_after_seconds, int) or retry_after_seconds <= 0:
        return result
    retry_after = _utcnow() + timedelta(seconds=retry_after_seconds)
    result["retry_after"] = retry_after.isoformat()
    result["retry_after_seconds"] = retry_after_seconds
    result["message"] = f"{message} Retry after {retry_after.isoformat()}."
    return result


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, YouTubeBotChallengeError):
        return BOT_CHALLENGE_MESSAGE
    if isinstance(exc, (YouTubeRateLimitError, YouTubeNetworkError, YouTubeUnavailableError)):
        return str(exc)
    if isinstance(exc, YouTubeError):
        return "YouTube could not provide this video to the server. Check that it is public and try again later."
    if isinstance(exc, StorageError):
        return "The source could not be saved to durable storage. Check storage configuration and try again."
    if isinstance(exc, (FFmpegNotFoundError, TranscriptionError, ValueError, RuntimeError)):
        return str(exc)
    return "Unable to analyze this video."


def _project_payload(video_id: str, url: str | None, title: str | None, source_path: Path | None) -> dict[str, Any]:
    payload = load_project_metadata(video_id) or {}
    payload.setdefault("video_id", video_id)
    if url is not None:
        payload["url"] = url
    if title is not None:
        payload["title"] = title
    if source_path is not None:
        payload["source_path"] = str(source_path)
        payload["source_url"] = f"/media/cache/{video_id}/{source_path.name}"
    payload.setdefault("status", "queued")
    payload.setdefault("candidate_count", 0)
    payload.setdefault("rendered_count", 0)
    return payload


def _start_source_analysis(
    video_id: str,
    *,
    url: str | None,
    title: str | None,
    owner_id: str | None,
    source_loader: Callable[[], dict[str, Any]],
    existing: dict[str, Any] | None = None,
    reuse_completed: bool = True,
    source_storage_key: str | None = None,
) -> AnalyzeResponse:
    if existing:
        status = str(existing.get("status", "unknown"))
        same_stored_upload = (
            source_storage_key
            and existing.get("source_storage_key") == source_storage_key
            and existing.get("owner_id") == owner_id
        )
        if status in {"queued", "running"}:
            if same_stored_upload:
                return AnalyzeResponse(
                    video_id=video_id,
                    status=status,
                    job_id=existing.get("analysis_job_id"),
                    title=existing.get("title"),
                    analysis_stage=existing.get("analysis_stage"),
                    message=existing.get("message"),
                    candidate_count=int(existing.get("candidate_count", 0)),
                    rendered_count=int(existing.get("rendered_count", 0)),
                )
            raise RuntimeError("This video is already being analyzed.")
        if status == "completed" and same_stored_upload:
            summary = project_summary(video_id) or {}
            return AnalyzeResponse(
                video_id=video_id,
                status="completed",
                job_id=existing.get("analysis_job_id"),
                title=summary.get("title"),
                analysis_stage=summary.get("analysis_stage"),
                message=summary.get("message"),
                candidate_count=int(summary.get("candidate_count", 0)),
                rendered_count=int(summary.get("rendered_count", 0)),
            )
        cooldown_error = _active_cooldown_error(existing)
        if cooldown_error is not None:
            raise cooldown_error
        if status == "completed" and reuse_completed and project_summary(video_id):
            summary = project_summary(video_id) or {}
            return AnalyzeResponse(
                video_id=video_id,
                status=str(summary.get("status", "completed")),
                title=summary.get("title"),
                analysis_stage=summary.get("analysis_stage"),
                message=summary.get("message"),
                candidate_count=int(summary.get("candidate_count", 0)),
                rendered_count=int(summary.get("rendered_count", 0)),
            )

    record = job_registry.create(
        "analysis",
        video_id=video_id,
        stage="queued",
        message="Queued",
    )

    queued_metadata = {
            "video_id": video_id,
            "url": url,
            "title": title or (existing.get("title") if existing else None),
            "owner_id": owner_id,
            "status": "queued",
            "analysis_stage": "queued",
            "message": "Queued",
            "candidate_count": int(existing.get("candidate_count", 0)) if existing else 0,
            "rendered_count": int(existing.get("rendered_count", 0)) if existing else 0,
            "analysis_job_id": record.id,
        }
    if source_storage_key is not None:
        queued_metadata["source_storage_key"] = source_storage_key
    save_project_metadata(video_id, queued_metadata)

    def _runner(job_id: str) -> None:
        try:
            job_registry.update(job_id, status="running", stage="preparing", message="Preparing")
            stage = "downloading" if url else "uploading"
            job_registry.update(job_id, stage=stage, message="Downloading" if url else "Uploading")
            downloaded = source_loader()
            video_id_local = video_id
            paths = cache_paths(video_id_local)
            source_path = Path(downloaded["filepath"])
            if source_storage_key is None:
                cached_source = paths["directory"] / f"source{source_path.suffix.casefold()}"
                cached_source.parent.mkdir(parents=True, exist_ok=True)
                if source_path.resolve() != cached_source.resolve():
                    shutil.copyfile(source_path, cached_source)
                source_path = cached_source
            source_key = source_storage_key or f"projects/{video_id_local}/source/{source_path.name}"
            if source_storage_key is None:
                storage.upload_file(source_path, source_key, mimetypes.guess_type(source_path.name)[0] or "video/mp4")
            metadata = _project_payload(video_id_local, url, downloaded.get("title"), source_path)
            metadata["owner_id"] = owner_id
            metadata["source_storage_key"] = source_key
            metadata.update(
                {
                    "status": "running",
                    "analysis_stage": stage,
                    "message": "Downloading" if url else "Uploading",
                    "analysis_job_id": job_id,
                }
            )
            try:
                duration = get_media_info(source_path).get("duration")
            except (OSError, RuntimeError, ValueError) as exc:
                _LOGGER.warning("Unable to inspect source duration for video %s: %s", video_id_local, exc)
            else:
                if isinstance(duration, (int, float)) and duration > 0:
                    metadata["source_duration"] = float(duration)
            save_project_metadata(video_id_local, metadata)

            config = load_config()
            job_registry.update(job_id, stage="transcribing", message="Transcribing")
            patch_project_metadata(video_id_local, status="running", analysis_stage="transcribing", message="Transcribing")

            job_registry.update(job_id, stage="detecting", message="Detecting Highlights")
            patch_project_metadata(video_id_local, status="running", analysis_stage="detecting", message="Detecting Highlights")
            candidates = run_media_task(detect_candidates, source_path, config, paths["transcript"])
            job_registry.update(job_id, stage="ranking", message="Detecting Highlights")
            patch_project_metadata(video_id_local, status="running", analysis_stage="ranking", message="Detecting Highlights")
            candidate_payload = {
                "source": source_path.name,
                "source_type": "youtube" if url else "upload",
                "source_url": url,
                "video_id": video_id_local,
                "title": downloaded.get("title"),
                "candidates": candidates,
            }
            save_candidates(video_id_local, candidate_payload)
            if paths["transcript"].is_file():
                storage.upload_file(paths["transcript"], f"projects/{video_id_local}/transcript.json", "application/json")
            storage.upload_file(paths["candidates"], f"projects/{video_id_local}/candidates.json", "application/json")

            metadata = load_project_metadata(video_id_local) or {}
            metadata.update(
                {
                    "url": url,
                    "title": downloaded.get("title"),
                    "source_path": str(source_path),
                    "source_url": f"/media/cache/{video_id_local}/{source_path.name}",
                    "status": "completed",
                    "analysis_stage": "complete",
                    "message": "Complete",
                    "candidate_count": len(candidates),
                    "analysis_job_id": job_id,
                }
            )
            save_project_metadata(video_id_local, metadata)
            summary = project_summary(video_id_local) or {}
            if downloaded.get("temporary") and source_storage_key is not None:
                Path(str(downloaded["filepath"])).unlink(missing_ok=True)
                downloaded["temporary"] = False
            job_registry.update(job_id, status="completed", stage="complete", message="Complete", result=summary)
        except Exception as exc:
            error_message = _friendly_error(exc)
            failure = _failure_metadata(exc, error_message)
            error_message = str(failure["message"])
            _LOGGER.error(
                "Analysis job %s failed for video %s (%s): %s",
                job_id,
                video_id,
                type(exc).__name__,
                error_message,
            )
            patch_project_metadata(
                video_id,
                status="failed",
                analysis_stage="failed",
                message=error_message,
                analysis_job_id=job_id,
                failure_code=failure["failure_code"],
                retry_after=failure["retry_after"],
                retry_after_seconds=failure["retry_after_seconds"],
            )
            job_registry.update(
                job_id,
                status="failed",
                stage="failed",
                message=error_message,
                error=error_message,
                result=failure,
            )
        finally:
            if isinstance(locals().get("downloaded"), dict) and downloaded.get("temporary"):
                try:
                    Path(str(downloaded["filepath"])).unlink(missing_ok=True)
                except (KeyError, OSError, TypeError, ValueError):
                    _LOGGER.warning("Unable to clean up temporary source for analysis job %s", job_id)

    thread = threading.Thread(target=_runner, args=(record.id,), daemon=True)
    thread.start()
    return AnalyzeResponse(
        video_id=video_id,
        status="queued",
        job_id=record.id,
        title=title or (existing.get("title") if existing else None),
        analysis_stage="queued",
        message="Queued",
        candidate_count=int(existing.get("candidate_count", 0)) if existing else 0,
        rendered_count=int(existing.get("rendered_count", 0)) if existing else 0,
    )


def start_analysis(url: str, *, force_download: bool = False, owner_id: str | None = None) -> AnalyzeResponse:
    source_video_id = extract_video_id(url)
    with _ANALYSIS_START_LOCK:
        existing = find_project_by_url(url, owner_id=owner_id)
        video_id = str(existing.get("video_id") or source_video_id) if existing else youtube_project_id(url, owner_id)

        scoped_metadata = load_project_metadata(video_id)
        if scoped_metadata is not None and existing is None:
            raise RuntimeError("Project not found.")

        def load_youtube_source() -> dict[str, Any]:
            provider = YouTubeProvider(
                url,
                force_download,
                lambda source_url, *, force_download=False: download_youtube_video(
                    source_url,
                    output_dir=_YOUTUBE_SOURCE_CACHE_DIR,
                    force_download=force_download,
                ),
            )
            return provider.ingest().__dict__

        return _start_source_analysis(
            video_id,
            url=url,
            title=None,
            owner_id=owner_id,
            existing=existing,
            source_loader=load_youtube_source,
            reuse_completed=not force_download,
        )


def start_uploaded_analysis(
    video_id: str,
    source_path: Path,
    *,
    filename: str,
    owner_id: str | None = None,
) -> AnalyzeResponse:
    return _start_source_analysis(
        video_id,
        url=None,
        title=filename,
        owner_id=owner_id,
        source_loader=lambda: {
            "video_id": video_id,
            "title": filename,
            "filepath": str(source_path),
            "cached": False,
            "temporary": True,
        },
    )


def start_stored_upload_analysis(
    video_id: str,
    source_storage_key: str,
    *,
    filename: str,
    owner_id: str,
    size_bytes: int,
) -> AnalyzeResponse:
    from backend.services.project_service import load_project_metadata

    existing = load_project_metadata(video_id)
    if existing and existing.get("owner_id") != owner_id:
        raise ValueError("Project not found.")
    if existing and existing.get("source_storage_key") not in {None, source_storage_key}:
        raise ValueError("The project already has a different source video.")

    def load_stored_source() -> dict[str, Any]:
        destination = PROCESSING_TEMP_DIR / "uploads" / "processing" / video_id / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            storage.download_file(source_storage_key, destination)
            if not destination.is_file() or destination.stat().st_size != size_bytes:
                raise StorageError("Uploaded source could not be restored from object storage.")
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {
            "video_id": video_id,
            "title": filename,
            "filepath": str(destination),
            "cached": False,
            "temporary": True,
        }

    return _start_source_analysis(
        video_id,
        url=None,
        title=filename,
        owner_id=owner_id,
        source_loader=load_stored_source,
        existing=existing,
        source_storage_key=source_storage_key,
        reuse_completed=False,
    )
