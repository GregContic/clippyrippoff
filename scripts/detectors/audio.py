"""Deterministic local audio energy and relative-spike detection."""
from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

from utils import PROCESSING_AUDIO_DIR, check_ffmpeg_available, run_subprocess


@dataclass
class AudioPeak:
    start: float
    end: float
    peak: float
    relative_peak: float


def extract_mono_wav(video_path: Path, sample_rate: int = 16000) -> Path:
    """Extract signed 16-bit mono PCM WAV for inexpensive standard-library analysis."""
    check_ffmpeg_available()
    PROCESSING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = PROCESSING_AUDIO_DIR / f"{video_path.stem}_detect.wav"
    run_subprocess(
        [
            "ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1",
            "-ar", str(sample_rate), "-acodec", "pcm_s16le", str(audio_path),
        ],
        f"Audio extraction for clip detection ({video_path.name})",
    )
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError(f"Audio extraction produced no data for {video_path.name}.")
    return audio_path


def _read_rms_windows(audio_path: Path, window_seconds: float) -> list[tuple[float, float]]:
    with wave.open(str(audio_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        if sample_width != 2 or channels != 1:
            raise RuntimeError("Detection audio must be mono 16-bit PCM WAV.")
        samples_per_window = max(1, round(sample_rate * window_seconds))
        values: list[tuple[float, float]] = []
        offset = 0
        while True:
            raw = wav_file.readframes(samples_per_window)
            if not raw:
                break
            sample_count = len(raw) // 2
            if not sample_count:
                break
            total = 0.0
            peak = 0
            for index in range(0, len(raw) - 1, 2):
                sample = int.from_bytes(raw[index:index + 2], "little", signed=True)
                magnitude = abs(sample)
                total += sample * sample
                peak = max(peak, magnitude)
            rms = math.sqrt(total / sample_count) / 32768.0
            values.append((offset / sample_rate, rms))
            offset += sample_count
        return values


def detect_audio_peaks(
    audio_path: Path,
    window_seconds: float = 0.25,
    baseline_seconds: float = 8.0,
    relative_threshold: float = 1.8,
    min_peak: float = 0.08,
) -> list[AudioPeak]:
    """Find local RMS spikes relative to a rolling mean baseline.

    The baseline excludes the current window and uses nearby windows, so a
    consistently loud section does not win merely by being loud globally.
    """
    windows = _read_rms_windows(audio_path, window_seconds)
    radius = max(1, round(baseline_seconds / window_seconds / 2))
    raw_peaks: list[AudioPeak] = []
    for index, (start, rms) in enumerate(windows):
        neighbors = [value for pos, (_, value) in enumerate(windows) if abs(pos - index) <= radius and pos != index]
        baseline = sum(neighbors) / len(neighbors) if neighbors else max(rms, 1e-6)
        relative = rms / max(baseline, 1e-6)
        if rms >= min_peak and relative >= relative_threshold:
            raw_peaks.append(AudioPeak(start, start + window_seconds, min(1.0, rms), relative))

    merged: list[AudioPeak] = []
    for peak in raw_peaks:
        if merged and peak.start <= merged[-1].end + window_seconds:
            previous = merged[-1]
            previous.end = peak.end
            previous.peak = max(previous.peak, peak.peak)
            previous.relative_peak = max(previous.relative_peak, peak.relative_peak)
        else:
            merged.append(peak)
    return merged
