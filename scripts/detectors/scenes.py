"""Lightweight frame-difference scene-change detection via FFmpeg raw video."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from utils import FFmpegNotFoundError, check_ffmpeg_available


@dataclass
class SceneChange:
    start: float
    end: float
    change_score: float


def _read_frame(stream: BinaryIO, frame_size: int) -> bytes:
    frame = bytearray()
    while len(frame) < frame_size:
        chunk = stream.read(frame_size - len(frame))
        if not chunk:
            break
        frame.extend(chunk)
    return bytes(frame)


def detect_scene_changes(
    video_path: Path,
    sample_fps: float = 1.0,
    threshold: float = 0.18,
    max_width: int = 320,
) -> list[SceneChange]:
    """Compare adjacent low-resolution grayscale frames without buffering the video."""
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
    frame_size = width * height
    changes: list[SceneChange] = []
    previous: bytes | None = None
    frame_index = 0
    process: subprocess.Popen[bytes] | None = None

    try:
        with tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=stderr,
            )
            assert process.stdout is not None
            try:
                while True:
                    frame = _read_frame(process.stdout, frame_size)
                    if len(frame) != frame_size:
                        break
                    if previous is not None:
                        difference = sum(abs(a - b) for a, b in zip(frame, previous)) / (frame_size * 255)
                        if difference >= threshold:
                            start = (frame_index - 1) / sample_fps
                            changes.append(SceneChange(start, frame_index / sample_fps, min(1.0, difference)))
                    previous = frame
                    frame_index += 1
                return_code = process.wait()
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait()

            if return_code != 0:
                stderr.seek(max(0, stderr.tell() - 8192))
                error = stderr.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Scene analysis failed for {video_path.name}: {error}")
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError("FFmpeg was not found while running scene detection.") from exc

    return changes
