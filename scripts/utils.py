"""Shared utilities for the gaming-shorts pipeline.

Small, dependency-free helpers used by both transcribe.py and make_short.py:
config loading, FFmpeg discovery/invocation, ffprobe inspection, timestamp
parsing/validation, and output filename generation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Project root is the parent of the "scripts" directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"
INPUT_VIDEOS_DIR = PROJECT_ROOT / "input" / "videos"
OUTPUT_SHORTS_DIR = PROJECT_ROOT / "output" / "shorts"
PROCESSING_AUDIO_DIR = PROJECT_ROOT / "processing" / "audio"
PROCESSING_TEMP_DIR = PROJECT_ROOT / "processing" / "temp"

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe cannot be found in PATH."""


class ValidationError(ValueError):
    """Raised for invalid user-supplied input (timestamps, ranges, paths)."""


class TranscriptionError(RuntimeError):
    """Raised when Whisper transcription fails."""


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config/settings.json, raising a clear error if missing/malformed."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found at {path}. "
            "Create it (see README) before running the pipeline."
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Configuration file at {path} is not valid JSON: {exc}") from exc


def ensure_directories() -> None:
    """Create expected working directories if they don't already exist."""
    for d in (INPUT_VIDEOS_DIR, OUTPUT_SHORTS_DIR, PROCESSING_AUDIO_DIR, PROCESSING_TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def check_ffmpeg_available() -> None:
    """Raise FFmpegNotFoundError with a clear message if ffmpeg/ffprobe are missing."""
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise FFmpegNotFoundError(
            "FFmpeg was not found.\n\n"
            "Install FFmpeg and make sure `ffmpeg` (and `ffprobe`) are available in PATH.\n"
            "Windows: download from https://www.gyan.dev/ffmpeg/builds/ or `winget install ffmpeg`, "
            "then restart your terminal.\n\n"
            f"Missing executable(s): {', '.join(missing)}\n"
            "Then run the command again."
        )


def run_subprocess(args: list[str], description: str) -> subprocess.CompletedProcess:
    """Run a subprocess command, capturing output and raising a clear error on failure.

    Args are passed as a list (never shell=True) so paths with spaces/special
    characters are handled correctly on Windows without manual quoting.
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            f"Could not execute '{args[0]}'. Is it installed and in PATH?\n{exc}"
        ) from exc

    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-20:])
        raise RuntimeError(
            f"{description} failed (exit code {result.returncode}).\n"
            f"Command: {' '.join(args)}\n"
            f"FFmpeg/tool output:\n{stderr_tail}"
        )
    return result


def get_media_info(video_path: Path) -> dict[str, Any]:
    """Use ffprobe to inspect a media file. Returns width, height, duration, streams."""
    check_ffmpeg_available()
    args = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = run_subprocess(args, f"ffprobe inspection of {video_path.name}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse ffprobe output for {video_path}: {exc}") from exc

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format", {})

    width = video_streams[0].get("width") if video_streams else None
    height = video_streams[0].get("height") if video_streams else None
    duration = None
    if fmt.get("duration") is not None:
        duration = float(fmt["duration"])
    elif video_streams and video_streams[0].get("duration") is not None:
        duration = float(video_streams[0]["duration"])

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "has_video": bool(video_streams),
        "has_audio": bool(audio_streams),
        "raw": data,
    }


def parse_timestamp(value: str | float | int) -> float:
    """Parse a timestamp given as seconds ("32", "32.5") or "HH:MM:SS(.ms)"."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip()
        if ":" in text:
            parts = text.split(":")
            if len(parts) not in (2, 3):
                raise ValidationError(f"Invalid timestamp format: '{value}'")
            try:
                parts_f = [float(p) for p in parts]
            except ValueError as exc:
                raise ValidationError(f"Invalid timestamp format: '{value}'") from exc
            seconds = 0.0
            for part in parts_f:
                seconds = seconds * 60 + part
        else:
            try:
                seconds = float(text)
            except ValueError as exc:
                raise ValidationError(f"Invalid timestamp: '{value}'. Use seconds or HH:MM:SS.") from exc

    if seconds < 0:
        raise ValidationError(f"Timestamp cannot be negative: {value}")
    return seconds


def validate_clip_range(
    start: float,
    end: float,
    min_seconds: float,
    max_seconds: float,
    video_duration: float | None = None,
) -> None:
    """Validate a start/end clip range, raising ValidationError on any problem."""
    if start < 0:
        raise ValidationError(f"Start timestamp ({start}s) cannot be negative.")
    if end <= start:
        raise ValidationError(
            f"End timestamp ({end}s) must be after start timestamp ({start}s)."
        )
    duration = end - start
    if duration < min_seconds:
        raise ValidationError(
            f"Clip duration ({duration:.2f}s) is shorter than the configured minimum "
            f"({min_seconds}s)."
        )
    if duration > max_seconds:
        raise ValidationError(
            f"Clip duration ({duration:.2f}s) exceeds the configured maximum "
            f"({max_seconds}s)."
        )
    if video_duration is not None and end > video_duration:
        raise ValidationError(
            f"End timestamp ({end}s) is beyond the source video's duration "
            f"({video_duration:.2f}s)."
        )


def generate_output_filename(output_dir: Path, prefix: str = "short", ext: str = ".mp4") -> Path:
    """Generate a predictable, non-colliding filename like short_2026-09-22_001.mp4."""
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    index = 1
    while True:
        candidate = output_dir / f"{prefix}_{today}_{index:03d}{ext}"
        if not candidate.exists():
            return candidate
        index += 1


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


def load_transcript(transcript_path: Path) -> dict[str, Any]:
    """Load and validate a transcript JSON file produced by transcribe.py."""
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")
    try:
        with transcript_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed transcript JSON at {transcript_path}: {exc}") from exc

    if "segments" not in data or not isinstance(data["segments"], list):
        raise ValueError(f"Malformed transcript at {transcript_path}: missing 'segments' list.")
    for i, seg in enumerate(data["segments"]):
        for key in ("start", "end", "text"):
            if key not in seg:
                raise ValueError(f"Malformed transcript segment #{i}: missing '{key}'.")
    return data


def transcript_path_for_video(video_path: Path) -> Path:
    """Return the expected transcript JSON path for a given source video."""
    return PROCESSING_TEMP_DIR / f"{video_path.stem}.json"
