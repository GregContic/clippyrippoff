"""Lightweight frame-difference scene-change detection via FFmpeg raw video."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils import FFmpegNotFoundError, check_ffmpeg_available


@dataclass
class SceneChange:
    start: float
    end: float
    change_score: float


def detect_scene_changes(
    video_path: Path,
    sample_fps: float = 1.0,
    threshold: float = 0.18,
    max_width: int = 320,
) -> list[SceneChange]:
    """Compare adjacent low-resolution grayscale frames.

    This is deliberately conservative and only supplies a supporting signal;
    gameplay camera motion and flashes can produce false positives.
    """
    check_ffmpeg_available()
    if sample_fps <= 0:
        raise ValueError("Scene sample_fps must be greater than zero.")
    width = max(16, int(max_width))
    height = max(16, round(width * 9 / 16))
    args = [
        "ffmpeg", "-v", "error", "-i", str(video_path), "-vf",
        f"fps={sample_fps},scale={width}:{height},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    try:
        result = subprocess.run(args, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError("FFmpeg was not found while running scene detection.") from exc
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Scene analysis failed for {video_path.name}: {error}")
    frame_size = width * height
    frames = [result.stdout[offset:offset + frame_size] for offset in range(0, len(result.stdout), frame_size)]
    changes: list[SceneChange] = []
    previous: bytes | None = None
    for index, frame in enumerate(frames):
        if len(frame) != frame_size:
            continue
        if previous is not None:
            difference = sum(abs(a - b) for a, b in zip(frame, previous)) / (frame_size * 255)
            if difference >= threshold:
                start = (index - 1) / sample_fps
                changes.append(SceneChange(start, index / sample_fps, min(1.0, difference)))
        previous = frame
    return changes
