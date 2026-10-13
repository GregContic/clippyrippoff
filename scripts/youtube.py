"""YouTube source acquisition only.

This module validates supported public YouTube URL shapes, downloads a
reasonable MP4-compatible source with yt-dlp, and manages a stable local cache.
It does not transcribe, detect, render, publish, or bypass access controls.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from utils import PROCESSING_TEMP_DIR

YOUTUBE_CACHE_DIR = PROCESSING_TEMP_DIR / "youtube"
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}$")
_LOGGER = logging.getLogger(__name__)
_DOWNLOAD_LOCKS: dict[str, threading.Lock] = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()
_EXTRACTION_COOLDOWNS: dict[str, tuple[float, str]] = {}
_EXTRACTION_COOLDOWNS_GUARD = threading.Lock()
NETWORK_MAX_ATTEMPTS = 3
NETWORK_RETRY_BASE_SECONDS = 1.0
NETWORK_RETRY_CAP_SECONDS = 4.0
NETWORK_RETRY_JITTER_SECONDS = 0.5
YOUTUBE_SOCKET_TIMEOUT_SECONDS = 20
RATE_LIMIT_COOLDOWN_SECONDS = 300
BOT_CHALLENGE_COOLDOWN_SECONDS = 900
BOT_CHALLENGE_MESSAGE = (
    "YouTube requires sign-in verification before this video can be downloaded. "
    "Analysis failed; try again later or use the Upload video option."
)
RATE_LIMIT_MESSAGE = (
    "YouTube is rate-limiting this request. Wait before trying this source again, "
    "or upload the video directly."
)


class YouTubeError(RuntimeError):
    """Raised for invalid URLs, unavailable videos, or download failures."""

    failure_code = "youtube_error"
    default_cooldown_seconds: int | None = None

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = (
            retry_after_seconds
            if retry_after_seconds is not None
            else self.default_cooldown_seconds
        )


class InvalidYouTubeURLError(YouTubeError):
    """Raised when a URL is not a supported YouTube URL."""


class YouTubeBotChallengeError(YouTubeError):
    """Raised when YouTube blocks extraction with a bot-verification challenge."""

    failure_code = "youtube_bot_challenge"
    default_cooldown_seconds = BOT_CHALLENGE_COOLDOWN_SECONDS


class YouTubeRateLimitError(YouTubeError):
    """Raised when YouTube rate-limits extraction."""

    failure_code = "youtube_rate_limited"
    default_cooldown_seconds = RATE_LIMIT_COOLDOWN_SECONDS


class YouTubeUnavailableError(YouTubeError):
    """Raised when a video is private, removed, or otherwise unavailable."""


class YouTubeNetworkError(YouTubeError):
    """Raised when extraction fails because of a transient network error."""


class YouTubeStorageError(YouTubeError):
    """Raised when the downloaded source cannot be stored locally."""


def _safe_diagnostic(message: str) -> str:
    message = re.sub(r"(https?://[^\s?#]+)\?[^\s#]*", r"\1?[REDACTED]", message)
    message = re.sub(
        r"(?i)\b(cookie|authorization|token|po(?:[_ -]?token)|visitor(?:[_ -]?data)|password|api[_-]?key)\b"
        r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
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


def _classify_extraction_error(exc: Exception) -> YouTubeError:
    message = str(exc).casefold()
    if (
        ("sign in to confirm" in message and "not a bot" in message)
        or "missing required visitor data" in message
        or "unable to fetch gvs po token" in message
    ):
        return YouTubeBotChallengeError(BOT_CHALLENGE_MESSAGE)
    if any(marker in message for marker in ("http error 429", "too many requests", "rate limit")):
        return YouTubeRateLimitError(RATE_LIMIT_MESSAGE)
    if any(marker in message for marker in ("private video", "video unavailable", "members-only", "copyright owner")):
        return YouTubeUnavailableError(
            "This YouTube video is private, unavailable, or restricted. Check access or upload an authorized copy."
        )
    if any(
        marker in message
        for marker in (
            "timed out",
            "timeout",
            "temporary failure",
            "connection reset",
            "connection aborted",
            "connection refused",
            "network is unreachable",
            "remote end closed connection",
            "remote disconnected",
            "name or service not known",
            "http error 500",
            "http error 502",
            "http error 503",
            "http error 504",
        )
    ):
        return YouTubeNetworkError(
            "The YouTube request timed out or failed temporarily. Check the connection and try again."
        )
    return YouTubeError(
        "The YouTube video could not be accessed. Check that it is public and try again later."
    )


def _lock_for_video(video_id: str) -> threading.Lock:
    with _DOWNLOAD_LOCKS_GUARD:
        return _DOWNLOAD_LOCKS.setdefault(video_id, threading.Lock())


def _cooldown_state(video_id: str) -> tuple[float, str] | None:
    with _EXTRACTION_COOLDOWNS_GUARD:
        state = _EXTRACTION_COOLDOWNS.get(video_id)
    if state is None:
        return None
    expires, failure_code = state
    if time.monotonic() >= expires:
        with _EXTRACTION_COOLDOWNS_GUARD:
            _EXTRACTION_COOLDOWNS.pop(video_id, None)
        return None
    return expires, failure_code


def _enforce_cooldown(video_id: str) -> None:
    state = _cooldown_state(video_id)
    if state is None:
        return
    expires, failure_code = state
    remaining = max(1, int(expires - time.monotonic()))
    if failure_code == YouTubeBotChallengeError.failure_code:
        raise YouTubeBotChallengeError(
            f"{BOT_CHALLENGE_MESSAGE} Retry after the {remaining}-second cooldown.",
            retry_after_seconds=remaining,
        )
    raise YouTubeRateLimitError(
        f"YouTube is rate-limiting this source. Retry after {remaining} seconds or upload the video directly.",
        retry_after_seconds=remaining,
    )


def _remember_cooldown(video_id: str, error: YouTubeError) -> None:
    seconds = error.retry_after_seconds
    if seconds is None:
        return
    with _EXTRACTION_COOLDOWNS_GUARD:
        _EXTRACTION_COOLDOWNS[video_id] = (
            time.monotonic() + seconds,
            error.failure_code,
        )


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, YouTubeNetworkError)


def _retry_delay(attempt: int) -> float:
    exponential = min(
        NETWORK_RETRY_CAP_SECONDS,
        NETWORK_RETRY_BASE_SECONDS * (2 ** attempt),
    )
    return exponential + random.uniform(0.0, NETWORK_RETRY_JITTER_SECONDS)


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

    _enforce_cooldown(video_id)
    lock = _lock_for_video(video_id)
    if not lock.acquire(blocking=False):
        raise YouTubeError("This YouTube source is already being downloaded. Please wait a moment and try again.")
    try:
        _enforce_cooldown(video_id)
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
            "socket_timeout": YOUTUBE_SOCKET_TIMEOUT_SECONDS,
            "retries": 0,
            "fragment_retries": 0,
            "extractor_retries": 0,
            "file_access_retries": 0,
            "logger": _YouTubeDLLogger(),
            "progress_hooks": [_progress_hook],
        }
        info: dict[str, Any] | None = None
        for attempt in range(NETWORK_MAX_ATTEMPTS):
            try:
                with yt_dlp.YoutubeDL(options) as downloader:
                    info = downloader.extract_info(url, download=True)
                break
            except Exception as exc:
                classified = _classify_extraction_error(exc)
                _LOGGER.warning(
                    "YouTube extraction failed for video %s (attempt %d, %s): %s",
                    video_id,
                    attempt + 1,
                    type(classified).__name__,
                    _safe_diagnostic(str(exc)),
                )
                if isinstance(classified, (YouTubeBotChallengeError, YouTubeRateLimitError)):
                    _remember_cooldown(video_id, classified)
                    raise classified from None
                if not _is_retryable(classified) or attempt == NETWORK_MAX_ATTEMPTS - 1:
                    raise classified from None
                time.sleep(_retry_delay(attempt))

        source = _cached_source(cache_dir)
        if source is None:
            raise YouTubeStorageError("Download completed but no readable source video was created.")
        title = str((info or {}).get("title") or video_id)
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
    finally:
        lock.release()


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
