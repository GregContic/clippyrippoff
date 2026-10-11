from __future__ import annotations

import logging
import mimetypes
import threading
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
from scripts.utils import FFmpegNotFoundError, TranscriptionError, load_config
from backend.services.storage import storage
from backend.services.storage import StorageError
from backend.services.ingestion import YouTubeProvider

_LOGGER = logging.getLogger(__name__)


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
) -> AnalyzeResponse:
    if existing:
        status = str(existing.get("status", "unknown"))
        if status == "running":
            raise RuntimeError("This video is already being analyzed.")
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

    save_project_metadata(
        video_id,
        {
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
        },
    )

    def _runner(job_id: str) -> None:
        try:
            job_registry.update(job_id, status="running", stage="preparing", message="Preparing")
            stage = "downloading" if url else "uploading"
            job_registry.update(job_id, stage=stage, message="Downloading" if url else "Uploading")
            downloaded = source_loader()
            video_id_local = downloaded["video_id"]
            paths = cache_paths(video_id_local)
            source_path = Path(downloaded["filepath"])
            source_key = f"projects/{video_id_local}/source/{source_path.name}"
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
            save_project_metadata(video_id_local, metadata)

            config = load_config()
            job_registry.update(job_id, stage="transcribing", message="Transcribing")
            patch_project_metadata(video_id_local, status="running", analysis_stage="transcribing", message="Transcribing")

            job_registry.update(job_id, stage="detecting", message="Detecting Highlights")
            patch_project_metadata(video_id_local, status="running", analysis_stage="detecting", message="Detecting Highlights")
            candidates = detect_candidates(source_path, config, paths["transcript"])
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
            job_registry.update(job_id, status="completed", stage="complete", message="Complete", result=summary)
        except Exception as exc:
            error_message = _friendly_error(exc)
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
            )
            job_registry.update(
                job_id,
                status="failed",
                stage="failed",
                message=error_message,
                error=error_message,
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
    video_id = extract_video_id(url)
    return _start_source_analysis(
        video_id,
        url=url,
        title=None,
        owner_id=owner_id,
        existing=find_project_by_url(url),
        source_loader=lambda: YouTubeProvider(url, force_download, download_youtube_video).ingest().__dict__,
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
