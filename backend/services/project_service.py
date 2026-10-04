from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core import PROJECT_ROOT
from backend.services.job_registry import job_registry
from backend.services.storage import S3Storage, storage
from scripts.utils import OUTPUT_SHORTS_DIR, PROCESSING_TEMP_DIR, get_media_info, run_subprocess


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


PROJECT_CACHE_DIR = PROCESSING_TEMP_DIR / "youtube"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def project_dir(video_id: str) -> Path:
    if not isinstance(video_id, str) or not VIDEO_ID_PATTERN.fullmatch(video_id):
        raise ValueError("Invalid video ID.")
    return PROJECT_CACHE_DIR / video_id


def metadata_path(video_id: str) -> Path:
    return project_dir(video_id) / "metadata.json"


def candidates_path(video_id: str) -> Path:
    return project_dir(video_id) / "candidates.json"


def manual_trims_path(video_id: str) -> Path:
    return project_dir(video_id) / "manual_trims.json"


def editor_state_path(video_id: str) -> Path:
    return project_dir(video_id) / "editor_state.json"


def transcript_path(video_id: str) -> Path:
    return project_dir(video_id) / "transcript.json"


def source_path(video_id: str) -> Path | None:
    directory = project_dir(video_id)
    if not directory.exists():
        return None
    for candidate in sorted(directory.glob("source.*")):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        key = _storage_key(path)
        if key is None or not isinstance(storage, S3Storage) or not storage.exists(key):
            return None
        try:
            payload = json.loads(storage.get_bytes(key).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)
    key = _storage_key(path)
    if key is not None and isinstance(storage, S3Storage):
        storage.put_bytes(key, json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), "application/json")


def _storage_key(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(PROCESSING_TEMP_DIR.resolve())
    except ValueError:
        return None
    return f"state/{str(relative).replace(chr(92), '/')}"


def load_project_metadata(video_id: str) -> dict[str, Any] | None:
    return read_json(metadata_path(video_id))


def save_project_metadata(video_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    data.setdefault("video_id", video_id)
    data.setdefault("created_at", _now())
    data["updated_at"] = _now()
    write_json(metadata_path(video_id), data)
    return data


def patch_project_metadata(video_id: str, **updates: Any) -> dict[str, Any]:
    current = load_project_metadata(video_id) or {}
    current.update(updates)
    return save_project_metadata(video_id, current)


def save_candidates(video_id: str, payload: dict[str, Any]) -> Path:
    path = candidates_path(video_id)
    write_json(path, payload)
    return path


def load_candidates(video_id: str) -> dict[str, Any] | None:
    return read_json(candidates_path(video_id))


def load_manual_trims(video_id: str) -> dict[str, Any] | None:
    return read_json(manual_trims_path(video_id))


def save_manual_trims(video_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    write_json(manual_trims_path(video_id), payload)
    return payload


def load_editor_state(video_id: str) -> dict[str, Any] | None:
    payload = read_json(editor_state_path(video_id))
    if payload is not None:
        return payload
    trims = load_manual_trims(video_id)
    if trims is None:
        return None
    candidates: dict[str, Any] = {}
    trims_map = trims.get("trims", {})
    if isinstance(trims_map, dict):
        for candidate_id, trim in trims_map.items():
            if isinstance(trim, dict):
                candidates[str(candidate_id)] = {
                    "trim": trim,
                    "caption_segments": [],
                    "render_settings": {},
                    "selected": False,
                }
    return {"video_id": video_id, "selected_candidate_id": None, "candidates": candidates}


def save_editor_state(video_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    data.setdefault("video_id", video_id)
    data.setdefault("selected_candidate_id", None)
    data.setdefault("candidates", {})
    write_json(editor_state_path(video_id), data)
    return data


def has_editor_state(video_id: str) -> bool:
    return editor_state_path(video_id).exists() or manual_trims_path(video_id).exists()


def get_candidate_editor_state(video_id: str, candidate_id: int) -> dict[str, Any]:
    state = load_editor_state(video_id) or {"video_id": video_id, "selected_candidate_id": None, "candidates": {}}
    candidates = state.get("candidates", {})
    if not isinstance(candidates, dict):
        candidates = {}
    candidate_state = candidates.get(str(candidate_id), {})
    return candidate_state if isinstance(candidate_state, dict) else {}


def set_candidate_editor_state(video_id: str, candidate_id: int, candidate_state: dict[str, Any]) -> dict[str, Any]:
    state = load_editor_state(video_id) or {"video_id": video_id, "selected_candidate_id": None, "candidates": {}}
    candidates = state.get("candidates", {})
    if not isinstance(candidates, dict):
        candidates = {}
    candidates[str(candidate_id)] = candidate_state
    state["video_id"] = video_id
    state["candidates"] = candidates
    trim = candidate_state.get("trim")
    if isinstance(trim, dict):
        trims = load_manual_trims(video_id) or {"video_id": video_id, "trims": {}}
        trims_map = trims.get("trims", {})
        if not isinstance(trims_map, dict):
            trims_map = {}
        trims_map[str(candidate_id)] = {"start": trim.get("start"), "end": trim.get("end")}
        trims["video_id"] = video_id
        trims["trims"] = trims_map
        save_manual_trims(video_id, trims)
    return save_editor_state(video_id, state)


def set_selected_candidate(video_id: str, candidate_id: int | None) -> dict[str, Any]:
    state = load_editor_state(video_id) or {"video_id": video_id, "selected_candidate_id": None, "candidates": {}}
    state["selected_candidate_id"] = candidate_id
    return save_editor_state(video_id, state)


def get_manual_trim(video_id: str, candidate_id: int) -> dict[str, Any] | None:
    payload = load_manual_trims(video_id)
    if not payload:
        return None
    trims = payload.get("trims", {})
    if not isinstance(trims, dict):
        return None
    trim = trims.get(str(candidate_id))
    if not isinstance(trim, dict):
        return None
    return trim


def set_manual_trim(video_id: str, candidate_id: int, start: float, end: float) -> dict[str, Any]:
    current = load_manual_trims(video_id) or {"video_id": video_id, "trims": {}}
    trims = current.get("trims", {})
    if not isinstance(trims, dict):
        trims = {}
    trims[str(candidate_id)] = {"start": start, "end": end}
    current["video_id"] = video_id
    current["trims"] = trims
    return save_manual_trims(video_id, current)


def get_candidate_count(video_id: str) -> int:
    payload = load_candidates(video_id)
    if not payload:
        return 0
    candidates = payload.get("candidates", [])
    return len(candidates) if isinstance(candidates, list) else 0


def _rendered_outputs(metadata: dict[str, Any]) -> list[str]:
    outputs = metadata.get("rendered_outputs", [])
    return [str(output) for output in outputs if isinstance(output, str)]


def register_render_output(video_id: str, filename: str) -> dict[str, Any]:
    metadata = load_project_metadata(video_id) or {}
    rendered_outputs = _rendered_outputs(metadata)
    if filename not in rendered_outputs:
        rendered_outputs.append(filename)
    metadata["rendered_outputs"] = rendered_outputs
    metadata["rendered_count"] = len(rendered_outputs)
    return save_project_metadata(video_id, metadata)


def _thumbnail_url(video_id: str, metadata: dict[str, Any]) -> str | None:
    thumbnail_value = metadata.get("thumbnail_url") or metadata.get("thumbnail_path") or metadata.get("thumbnail")
    if isinstance(thumbnail_value, str) and thumbnail_value.strip():
        if thumbnail_value.startswith("/"):
            return thumbnail_value
        thumbnail_path = project_dir(video_id) / thumbnail_value
        if thumbnail_path.exists():
            return f"/media/cache/{video_id}/{thumbnail_path.name}"
    directory = project_dir(video_id)
    for candidate in sorted(directory.glob("thumbnail.*")):
      if candidate.is_file() and candidate.stat().st_size > 0:
            return f"/media/cache/{video_id}/{candidate.name}"
    return None


def _ensure_thumbnail_url(video_id: str, metadata: dict[str, Any]) -> str | None:
    existing = _thumbnail_url(video_id, metadata)
    if existing:
        return existing

    source = source_path(video_id)
    if source is None:
        return None

    thumbnail_path = project_dir(video_id) / "thumbnail.jpg"
    try:
        duration = source_duration(video_id) or 0.0
        timestamp = max(duration / 2.0, 0.0)
        temporary_path = thumbnail_path.with_suffix(".tmp.jpg")
        run_subprocess(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(temporary_path),
            ],
            f"Thumbnail extraction for {video_id}",
        )
        if not temporary_path.exists() or temporary_path.stat().st_size == 0:
            return None
        temporary_path.replace(thumbnail_path)
        if isinstance(storage, S3Storage):
            storage.upload_file(thumbnail_path, f"projects/{video_id}/cache/{thumbnail_path.name}", "image/jpeg")
    except (OSError, RuntimeError, ValueError):
        return None
    return f"/media/cache/{video_id}/{thumbnail_path.name}"


def _render_jobs_for_video(video_id: str) -> list[Any]:
    return [record for record in job_registry.list() if record.kind == "render" and record.video_id == video_id]


def _analysis_job_for(video_id: str, metadata: dict[str, Any]) -> Any | None:
    job_id = metadata.get("analysis_job_id")
    if isinstance(job_id, str):
        record = job_registry.get(job_id)
        if record is not None and record.kind == "analysis":
            return record
    for record in job_registry.list():
        if record.kind == "analysis" and record.video_id == video_id:
            return record
    return None


def _render_job_counts(jobs: list[Any]) -> dict[str, int]:
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "interrupted": 0}
    for job in jobs:
        if job.status in counts:
            counts[job.status] += 1
    return counts


def _latest_timestamp(*values: str | None) -> str | None:
    parsed: list[datetime] = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append(datetime.fromisoformat(value))
        except ValueError:
            continue
    if not parsed:
        return None
    return max(parsed).isoformat()


def project_render_jobs(video_id: str) -> list[dict[str, Any]]:
    jobs = _render_jobs_for_video(video_id)
    return [job.to_dict() for job in jobs]


def project_files(video_id: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    jobs = _render_jobs_for_video(video_id)
    job_lookup: dict[str, Any] = {}
    for job in jobs:
        output_name = None
        if job.output_path:
            output_name = Path(job.output_path).name
        elif job.output_url:
            output_name = Path(str(job.output_url)).name
        if output_name:
            job_lookup[output_name] = job
    for job in jobs:
        output_name = None
        if job.output_path:
            output_name = Path(job.output_path).name
        elif job.output_url:
            output_name = Path(str(job.output_url)).name
        if not output_name or output_name in seen:
            continue
        seen.add(output_name)
        output_file = OUTPUT_SHORTS_DIR / output_name
        duration = None
        request_signature = job.result.get("request_signature") if isinstance(job.result, dict) else None
        if isinstance(request_signature, dict):
            start = request_signature.get("start")
            end = request_signature.get("end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                duration = float(end) - float(start)
        stat = output_file.stat() if output_file.exists() else None
        files.append(
            {
                "filename": output_name,
                "url": f"/media/shorts/{output_name}",
                "size_bytes": stat.st_size if stat is not None else 0,
                "created_at": job.updated_at,
                "duration": duration,
                "candidate_id": job.candidate_id,
                "render_job_id": job.id,
            }
        )
    return files


def find_project_by_url(url: str) -> dict[str, Any] | None:
    from youtube import extract_video_id

    video_id = extract_video_id(url)
    metadata = load_project_metadata(video_id)
    if not metadata:
        return None
    return metadata


def _source_url(video_id: str) -> str | None:
    source = source_path(video_id)
    if source is None:
        return None
    return f"/media/cache/{video_id}/{source.name}"


def _transcript_url(video_id: str) -> str | None:
    path = transcript_path(video_id)
    if not path.exists():
        return None
    return f"/media/cache/{video_id}/{path.name}"

    jobs = _render_jobs_for_video(video_id)
    return [job.to_dict() for job in jobs]


def project_files(video_id: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    jobs = _render_jobs_for_video(video_id)
    job_lookup: dict[str, Any] = {}
    for job in jobs:
        output_name = None
        if job.output_path:
            output_name = Path(job.output_path).name
        elif job.output_url:
            output_name = Path(str(job.output_url)).name
        if output_name:
            job_lookup[output_name] = job

    for job in jobs:
        if job.status not in {"completed", "failed", "interrupted"}:
            continue
        output_name = None
        if job.output_path:
            output_name = Path(job.output_path).name
        elif job.output_url:
            output_name = Path(str(job.output_url)).name
        if not output_name or output_name in seen:
            continue
        seen.add(output_name)
        output_file = OUTPUT_SHORTS_DIR / output_name
        stat = output_file.stat() if output_file.exists() else None
        duration = None
        request_signature = job.result.get("request_signature") if isinstance(job.result, dict) else None
        if isinstance(request_signature, dict):
            start = request_signature.get("start")
            end = request_signature.get("end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                duration = float(end) - float(start)
        files.append(
            {
                "filename": output_name,
                "url": f"/media/shorts/{output_name}",
                "size_bytes": stat.st_size if stat is not None else 0,
                "created_at": job.updated_at,
                "duration": duration,
                "candidate_id": job.candidate_id,
                "render_job_id": job.id,
            }
        )

    metadata = load_project_metadata(video_id) or {}
    for output_name in _rendered_outputs(metadata):
        if output_name in seen:
            continue
        seen.add(output_name)
        job = job_lookup.get(output_name)
        output_file = OUTPUT_SHORTS_DIR / output_name
        stat = output_file.stat() if output_file.exists() else None
        duration = None
        candidate_id = None
        render_job_id = None
        created_at = metadata.get("updated_at")
        if job is not None:
            candidate_id = job.candidate_id
            render_job_id = job.id
            created_at = job.updated_at
            request_signature = job.result.get("request_signature") if isinstance(job.result, dict) else None
            if isinstance(request_signature, dict):
                start = request_signature.get("start")
                end = request_signature.get("end")
                if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                    duration = float(end) - float(start)
        files.append(
            {
                "filename": output_name,
                "url": f"/media/shorts/{output_name}",
                "size_bytes": stat.st_size if stat is not None else 0,
                "created_at": created_at,
                "duration": duration,
                "candidate_id": candidate_id,
                "render_job_id": render_job_id,
            }
        )
    return files


def find_project_by_url(url: str) -> dict[str, Any] | None:
    from youtube import extract_video_id

    video_id = extract_video_id(url)
    metadata = load_project_metadata(video_id)
    if not metadata:
        return None
    return metadata


def _source_url(video_id: str) -> str | None:
    source = source_path(video_id)
    if source is None:
        return None
    return f"/media/cache/{video_id}/{source.name}"


def _transcript_url(video_id: str) -> str | None:
    path = transcript_path(video_id)
    if not path.exists():
        return None
    return f"/media/cache/{video_id}/{path.name}"


def _candidates_url(video_id: str) -> str | None:
    path = candidates_path(video_id)
    if not path.exists():
        return None
    return f"/media/cache/{video_id}/{path.name}"


def source_duration(video_id: str) -> float | None:
    source = source_path(video_id)
    if source is None:
        return None
    try:
        info = get_media_info(source)
    except Exception:
        return None
    duration = info.get("duration")
    return float(duration) if duration is not None else None


def project_summary(video_id: str) -> dict[str, Any] | None:
    metadata = load_project_metadata(video_id)
    if not metadata:
        return None
    candidate_count = int(metadata.get("candidate_count") or get_candidate_count(video_id))
    rendered_outputs = _rendered_outputs(metadata)
    render_jobs = _render_jobs_for_video(video_id)
    render_counts = _render_job_counts(render_jobs)
    analysis_job = _analysis_job_for(video_id, metadata)
    editor_state = load_editor_state(video_id)
    manual_trim_count = 0
    if isinstance(editor_state, dict):
        candidates = editor_state.get("candidates", {})
        if isinstance(candidates, dict):
            manual_trim_count = sum(1 for state in candidates.values() if isinstance(state, dict) and isinstance(state.get("trim"), dict))
    source_exists = source_path(video_id) is not None
    summary = {
        "video_id": video_id,
        "title": metadata.get("title"),
        "url": metadata.get("url"),
        "source_thumbnail_url": _ensure_thumbnail_url(video_id, metadata),
        "status": metadata.get("status", "unknown"),
        "analysis_stage": metadata.get("analysis_stage"),
        "message": metadata.get("message"),
        "candidate_count": candidate_count,
        "rendered_count": int(metadata.get("rendered_count") or len(rendered_outputs)),
        "source_duration": source_duration(video_id),
        "source_cache_status": "available" if source_exists else "missing",
        "project_created_at": metadata.get("created_at"),
        "last_analyzed_at": analysis_job.updated_at if analysis_job is not None else metadata.get("updated_at"),
        "latest_activity_at": _latest_timestamp(metadata.get("updated_at"), analysis_job.updated_at if analysis_job is not None else None, *(job.updated_at for job in render_jobs)),
        "saved_editing_state": editor_state is not None,
        "manual_trim_count": manual_trim_count,
        "render_job_count": len(render_jobs),
        "queued_render_jobs": render_counts["queued"],
        "running_render_jobs": render_counts["running"],
        "completed_render_jobs": render_counts["completed"],
        "failed_render_jobs": render_counts["failed"],
        "interrupted_render_jobs": render_counts["interrupted"],
        "generated_output_count": len(project_files(video_id)),
        "source_url": metadata.get("source_url"),
        "source_video_url": _source_url(video_id),
        "transcript_url": _transcript_url(video_id),
        "candidates_url": _candidates_url(video_id),
        "rendered_urls": [f"/media/shorts/{filename}" for filename in rendered_outputs],
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
        "analysis_job_id": metadata.get("analysis_job_id"),
    }
    return summary


def list_projects(limit: int = 25) -> list[dict[str, Any]]:
    if not PROJECT_CACHE_DIR.exists():
        return []
    items: list[dict[str, Any]] = []
    for metadata_file in PROJECT_CACHE_DIR.glob("*/metadata.json"):
        try:
            json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            summary = project_summary(metadata_file.parent.name)
        except ValueError:
            continue
        if summary is not None:
            items.append(summary)
    items.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return items[:limit]


def safe_output_path(filename: str) -> Path:
    candidate = (OUTPUT_SHORTS_DIR / filename).resolve()
    root = OUTPUT_SHORTS_DIR.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("Invalid output filename.")
    if candidate.suffix.lower() != ".mp4":
        raise ValueError("Only .mp4 files can be deleted through the library API.")
    return candidate


def list_library_items() -> list[dict[str, Any]]:
    if not OUTPUT_SHORTS_DIR.exists():
        return []
    items: list[dict[str, Any]] = []
    jobs_by_filename = {}
    for job in job_registry.list():
        if job.output_path:
            jobs_by_filename[Path(job.output_path).name] = job
    for path in sorted(OUTPUT_SHORTS_DIR.glob("*.mp4"), reverse=True):
        if not path.is_file():
            continue
        try:
            info = get_media_info(path)
        except Exception:
            info = {"duration": None}
        stat = path.stat()
        job = jobs_by_filename.get(path.name)
        items.append(
            {
                "filename": path.name,
                "url": f"/media/shorts/{path.name}",
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "duration": info.get("duration"),
                "review_status": job.review_status if job is not None else "pending_review",
                "render_job_id": job.id if job is not None else None,
            }
        )
    return items


def delete_library_item(filename: str) -> None:
    path = safe_output_path(filename)
    if not path.exists():
        raise FileNotFoundError(filename)
    path.unlink()
