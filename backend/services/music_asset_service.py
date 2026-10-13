from __future__ import annotations

import math
import mimetypes
import logging
import uuid
from pathlib import Path
from typing import BinaryIO

from backend.services.project_service import find_music_asset, list_music_assets, project_owner_id, save_music_asset
from backend.services.storage import StorageError, storage
from scripts.utils import PROCESSING_TEMP_DIR, get_media_info

MAX_MUSIC_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_MUSIC_DURATION_SECONDS = 30 * 60
ALLOWED_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
AUDIO_CONTENT_TYPES = {
    ".aac": {"audio/aac", "audio/x-aac"},
    ".flac": {"audio/flac", "audio/x-flac"},
    ".m4a": {"audio/mp4", "audio/x-m4a"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".ogg": {"audio/ogg", "application/ogg"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/vnd.wave"},
}
logger = logging.getLogger(__name__)


def upload_music_asset(
    video_id: str,
    *,
    owner_id: str,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> dict:
    if project_owner_id(video_id) != owner_id:
        raise FileNotFoundError("Project not found.")
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.casefold()
    if not safe_name or safe_name != filename or suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError("Upload an MP3, WAV, AAC, M4A, OGG, or FLAC audio file.")
    guessed_type = mimetypes.guess_type(safe_name)[0]
    accepted_types = AUDIO_CONTENT_TYPES[suffix]
    if content_type and content_type not in {"application/octet-stream", guessed_type, *accepted_types}:
        raise ValueError("The uploaded content type does not match a supported audio format.")
    expected_type = next((value for value in accepted_types if value.startswith("audio/")), guessed_type)

    asset_id = f"music-{uuid.uuid4().hex}"
    temporary_path = PROCESSING_TEMP_DIR / "music-uploads" / f"{asset_id}{suffix}"
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with temporary_path.open("wb") as output:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_MUSIC_UPLOAD_BYTES:
                    raise ValueError("Music uploads must be 50 MB or smaller.")
                output.write(chunk)
        if written == 0:
            raise ValueError("The uploaded audio file is empty.")
        info = get_media_info(temporary_path)
        if not info.get("has_audio"):
            raise ValueError("The uploaded file does not contain an audio stream.")
        duration_value = info.get("duration")
        if duration_value is None or not math.isfinite(float(duration_value)) or float(duration_value) <= 0:
            raise ValueError("The uploaded audio duration could not be determined.")
        duration = float(duration_value)
        if duration > MAX_MUSIC_DURATION_SECONDS:
            raise ValueError("Music tracks must be 30 minutes or shorter.")

        key = f"projects/{video_id}/music/{asset_id}/audio{suffix}"
        if storage.exists(key):
            raise RuntimeError("Music asset identity already exists; refusing to overwrite it.")
        storage.upload_file(temporary_path, key, expected_type or "application/octet-stream")
        asset = {
            "asset_id": asset_id,
            "project_id": video_id,
            "owner_id": owner_id,
            "filename": safe_name,
            "storage_key": key,
            "content_type": expected_type or "application/octet-stream",
            "size_bytes": written,
            "duration_seconds": duration,
        }
        try:
            save_music_asset(video_id, asset)
        except Exception:
            try:
                storage.delete(key)
            except StorageError:
                logger.exception("Could not remove unregistered music object %s", key)
            raise
        return {key: value for key, value in asset.items() if key not in {"owner_id", "storage_key"}}
    finally:
        temporary_path.unlink(missing_ok=True)


def list_project_music(video_id: str, *, owner_id: str) -> list[dict]:
    return list_music_assets(video_id, owner_id=owner_id)


def download_project_music(
    video_id: str,
    asset_id: str,
    *,
    owner_id: str,
    destination_dir: Path,
) -> Path:
    asset = find_music_asset(video_id, asset_id, owner_id=owner_id)
    if asset is None:
        raise FileNotFoundError("Project music asset not found.")
    key = asset.get("storage_key")
    suffix = Path(str(asset.get("filename", ""))).suffix.casefold()
    expected_prefix = f"projects/{video_id}/music/{asset_id}/"
    if (
        not isinstance(key, str)
        or not key.startswith(expected_prefix)
        or "/" in key[len(expected_prefix):]
        or suffix not in ALLOWED_AUDIO_EXTENSIONS
    ):
        raise ValueError("Project music asset metadata is invalid.")
    destination = destination_dir / f"{asset_id}{suffix}"
    storage.download_file(key, destination)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise FileNotFoundError("Project music asset could not be restored from durable storage.")
    return destination
