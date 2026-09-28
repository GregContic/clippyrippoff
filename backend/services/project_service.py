from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core import PROJECT_ROOT
from scripts.utils import OUTPUT_SHORTS_DIR, PROCESSING_TEMP_DIR, get_media_info


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


PROJECT_CACHE_DIR = PROCESSING_TEMP_DIR / "youtube"


def project_dir(video_id: str) -> Path:
    return PROJECT_CACHE_DIR / video_id


def metadata_path(video_id: str) -> Path:
    return project_dir(video_id) / "metadata.json"


def candidates_path(video_id: str) -> Path:
    return project_dir(video_id) / "candidates.json"


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


def project_summary(video_id: str) -> dict[str, Any] | None:
    metadata = load_project_metadata(video_id)
    if not metadata:
        return None
    candidate_count = int(metadata.get("candidate_count") or get_candidate_count(video_id))
    rendered_outputs = _rendered_outputs(metadata)
    summary = {
        "video_id": video_id,
        "title": metadata.get("title"),
        "url": metadata.get("url"),
        "status": metadata.get("status", "unknown"),
        "analysis_stage": metadata.get("analysis_stage"),
        "message": metadata.get("message"),
        "candidate_count": candidate_count,
        "rendered_count": int(metadata.get("rendered_count") or len(rendered_outputs)),
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
        summary = project_summary(metadata_file.parent.name)
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
    for path in sorted(OUTPUT_SHORTS_DIR.glob("*.mp4"), reverse=True):
        if not path.is_file():
            continue
        try:
            info = get_media_info(path)
        except Exception:
            info = {"duration": None}
        stat = path.stat()
        items.append(
            {
                "filename": path.name,
                "url": f"/media/shorts/{path.name}",
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "duration": info.get("duration"),
            }
        )
    return items


def delete_library_item(filename: str) -> None:
    path = safe_output_path(filename)
    if not path.exists():
        raise FileNotFoundError(filename)
    path.unlink()
