"""YouTube source acquisition only.

This module validates supported public YouTube URL shapes, downloads a
reasonable MP4-compatible source with yt-dlp, and manages a stable local cache.
It does not transcribe, detect, render, publish, or bypass access controls.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from utils import PROCESSING_TEMP_DIR

YOUTUBE_CACHE_DIR = PROCESSING_TEMP_DIR / "youtube"
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}$")
_LOGGER = logging.getLogger(__name__)
BOT_CHALLENGE_MESSAGE = (
    "YouTube requires sign-in verification before this video can be downloaded. "
    "Analysis failed; try again later."
)


class YouTubeError(RuntimeError):
    """Raised for invalid URLs, unavailable videos, or download failures."""


class InvalidYouTubeURLError(YouTubeError):
    """Raised when a URL is not a supported YouTube URL."""


class YouTubeBotChallengeError(YouTubeError):
    """Raised when YouTube blocks extraction with a bot-verification challenge."""


def _safe_diagnostic(message: str) -> str:
    message = re.sub(r"(https?://[^\s?#]+)\?[^\s#]*", r"\1?[REDACTED]", message)
    message = re.sub(
        r"(?i)\b(cookie|authorization|token|password|api[_-]?key)\b\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )
    return message[:500]


class _YouTubeDLLogger:
    def debug(self, message: str) -> None:
        _LOGGER.debug("yt-dlp: %s", _safe_diagnostic(str(message)))

    def warning(self, message: str) -> None:
        _LOGGER.warning("yt-dlp: %s", _safe_diagnostic(str(message)))

    def error(self, message: str) -> None:
        _LOGGER.error("yt-dlp: %s", _safe_diagnostic(str(message)))


def extract_video_id(url: str) -> str:
    """Extract a YouTube video ID from watch, youtu.be, or shorts URLs."""
    if not isinstance(url, str) or not url.strip():
        raise InvalidYouTubeURLError("Invalid YouTube URL.")
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().split(":", 1)[0]
    host = host[4:] if host.startswith("www.") else host

    video_id: str | None = None
    if host in {"youtube.com", "m.youtube.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] == "watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif len(parts) >= 2 and parts[0] in {"shorts", "embed"}:
            video_id = parts[1]
    elif host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]

    if not video_id or not _VIDEO_ID_PATTERN.fullmatch(video_id):
        raise InvalidYouTubeURLError("Invalid YouTube URL.")
    return video_id


def _cache_dir(video_id: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or YOUTUBE_CACHE_DIR) / video_id


def _cached_source(cache_dir: Path) -> Path | None:
    candidates = sorted(cache_dir.glob("source.*"))
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _load_yt_dlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise YouTubeError(
            "yt-dlp is not installed. Run `pip install -r requirements.txt` "
            "inside the existing virtual environment."
        ) from exc
    return yt_dlp


def download_youtube_video(
    url: str,
    output_dir: Path | None = None,
    force_download: bool = False,
) -> dict[str, Any]:
    """Download or reuse a cached public YouTube source.

    Returns only stable application metadata, not raw yt-dlp objects.
    """
    video_id = extract_video_id(url)
    cache_dir = _cache_dir(video_id, output_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_source = _cached_source(cache_dir)
    metadata_path = cache_dir / "metadata.json"
    if cached_source is not None and not force_download:
        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                import json
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
        return {
            "url": url,
            "video_id": video_id,
            "title": metadata.get("title", video_id),
            "filepath": str(cached_source),
            "cached": True,
        }

    yt_dlp = _load_yt_dlp()
    output_template = str(cache_dir / "source.%(ext)s")
    options = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": {"node": {}},
        "logger": _YouTubeDLLogger(),
        "progress_hooks": [_progress_hook],
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except Exception as exc:
        diagnostic = _safe_diagnostic(str(exc))
        _LOGGER.warning(
            "YouTube extraction failed for video %s (%s): %s",
            video_id,
            type(exc).__name__,
            diagnostic,
        )
        normalized_error = str(exc).casefold()
        if "sign in to confirm" in normalized_error and "not a bot" in normalized_error:
            raise YouTubeBotChallengeError(BOT_CHALLENGE_MESSAGE) from None
        raise YouTubeError(
            "The YouTube video could not be accessed. Check that it is public "
            "and try again later."
        ) from None

    source = _cached_source(cache_dir)
    if source is None:
        raise YouTubeError("Download completed but no readable source video was created.")
    title = str(info.get("title") or video_id)
    try:
        import json
        metadata_path.write_text(
            json.dumps({"url": url, "video_id": video_id, "title": title}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise YouTubeError(f"Downloaded video, but could not save cache metadata: {exc}") from exc
    return {
        "url": url,
        "video_id": video_id,
        "title": title,
        "filepath": str(source),
        "cached": False,
    }


def _progress_hook(status: dict[str, Any]) -> None:
    """Keep yt-dlp progress readable without dumping its normal log stream."""
    if status.get("status") == "finished":
        print("Download complete.")
    elif status.get("status") == "downloading":
        percent = str(status.get("_percent_str", "")).strip()
        if percent:
            print(f"Downloading: {percent}", end="\r")


def cache_paths(video_id: str, cache_dir: Path | None = None) -> dict[str, Path]:
    """Return stable paths used by the URL workflow."""
    directory = _cache_dir(video_id, cache_dir)
    return {
        "directory": directory,
        "transcript": directory / "transcript.json",
        "candidates": directory / "candidates.json",
    }
