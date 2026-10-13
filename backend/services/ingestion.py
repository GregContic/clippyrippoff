from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

class IngestionError(RuntimeError):
    """Raised when an ingestion source cannot be accepted."""


class IngestionProvider(Protocol):
    def ingest(self) -> "IngestedSource":
        ...


@dataclass(frozen=True)
class IngestedSource:
    video_id: str
    filepath: Path
    title: str
    source_url: str | None = None
    temporary: bool = False


ALLOWED_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".webm",
}
DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024


def max_upload_bytes() -> int:
    try:
        value = int(os.getenv("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))
    except ValueError as exc:
        raise IngestionError("MAX_UPLOAD_BYTES must be an integer.") from exc
    if value <= 0:
        raise IngestionError("MAX_UPLOAD_BYTES must be greater than zero.")
    return value


def validate_upload_name(filename: str | None) -> str:
    if not filename:
        raise IngestionError("Choose a video file to upload.")
    name = Path(filename).name
    if (
        name != filename
        or "/" in filename
        or "\\" in filename
        or Path(name).suffix.casefold() not in ALLOWED_EXTENSIONS
    ):
        raise IngestionError("Upload an MP4 or a video format supported by FFmpeg.")
    return name


def _check_space(directory: Path, required: int) -> None:
    try:
        available = shutil.disk_usage(directory).free
    except OSError as exc:
        raise IngestionError("Unable to verify available storage for the upload.") from exc
    if available < required:
        raise IngestionError("Not enough local storage is available for this upload.")


def save_uploaded_file(file: BinaryIO, filename: str, destination: Path) -> int:
    safe_name = validate_upload_name(filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    limit = max_upload_bytes()
    _check_space(destination.parent, 1)
    written = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise IngestionError(f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
                _check_space(destination.parent, len(chunk))
                output.write(chunk)
            output.flush()
        if written == 0:
            raise IngestionError("The uploaded file is empty.")
    except IngestionError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise IngestionError("The upload could not be stored locally.") from exc
    return written


def upload_temp_path(temp_dir: Path, video_id: str, filename: str) -> Path:
    safe_name = validate_upload_name(filename)
    return temp_dir / "uploads" / video_id / safe_name


class UploadedFileProvider:
    def __init__(self, video_id: str, filepath: Path, title: str) -> None:
        self.source = IngestedSource(video_id, filepath, title, temporary=True)

    def ingest(self) -> IngestedSource:
        if not self.source.filepath.is_file() or self.source.filepath.stat().st_size <= 0:
            raise IngestionError("The uploaded video is no longer available.")
        return self.source


class YouTubeProvider:
    def __init__(self, url: str, force_download: bool = False, downloader=None) -> None:
        self.url = url
        self.force_download = force_download
        self.downloader = downloader

    def ingest(self) -> IngestedSource:
        downloader = self.downloader
        if downloader is None:
            from scripts.youtube import download_youtube_video

            downloader = download_youtube_video
        result = downloader(self.url, force_download=self.force_download)
        return IngestedSource(
            video_id=str(result["video_id"]),
            filepath=Path(str(result["filepath"])),
            title=str(result.get("title") or result["video_id"]),
            source_url=self.url,
            temporary=False,
        )
