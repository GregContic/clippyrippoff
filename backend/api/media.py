from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from backend.services.project_service import load_project_metadata
from backend.services.storage import storage
from scripts.utils import OUTPUT_SHORTS_DIR, PROCESSING_TEMP_DIR

router = APIRouter(tags=["media"])


def _safe_name(name: str) -> str:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid media filename.")
    return name


@router.get("/api/media/cache/{video_id}/{filename}")
@router.get("/media/cache/{video_id}/{filename}")
def get_cached_media(video_id: str, filename: str):
    filename = _safe_name(filename)
    metadata = load_project_metadata(video_id) or {}
    if filename == Path(str(metadata.get("source_path", ""))).name:
        key = metadata.get("source_storage_key")
    elif filename in {"transcript.json", "candidates.json"}:
        key = f"projects/{video_id}/{filename}"
    else:
        key = f"projects/{video_id}/cache/{filename}"
    local = PROCESSING_TEMP_DIR / "youtube" / video_id / filename
    if local.is_file():
        return FileResponse(local)
    if not isinstance(key, str) or not storage.exists(key):
        raise HTTPException(status_code=404, detail="Media not found.")
    return StreamingResponse(storage.open_stream(key), media_type="application/octet-stream")


@router.get("/api/media/renders/{video_id}/{filename}")
@router.get("/media/renders/{video_id}/{filename}")
def get_render_media(video_id: str, filename: str):
    filename = _safe_name(filename)
    local = OUTPUT_SHORTS_DIR / filename
    if local.is_file():
        return FileResponse(local, media_type="video/mp4")
    key = f"projects/{video_id}/renders/{filename}"
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="Rendered media not found.")
    return StreamingResponse(storage.open_stream(key), media_type="video/mp4")


@router.get("/api/media/shorts/{filename}")
@router.get("/media/shorts/{filename}")
def get_legacy_render_media(filename: str):
    filename = _safe_name(filename)
    local = OUTPUT_SHORTS_DIR / filename
    if local.is_file():
        return FileResponse(local, media_type="video/mp4")
    for key in storage.list_keys("projects/"):
        if key.endswith(f"/renders/{filename}"):
            return StreamingResponse(storage.open_stream(key), media_type="video/mp4")
    raise HTTPException(status_code=404, detail="Rendered media not found.")
