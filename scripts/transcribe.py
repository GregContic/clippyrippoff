"""Transcribe gameplay videos in input/videos/ using local OpenAI Whisper.

Usage:
    python scripts/transcribe.py
    python scripts/transcribe.py --video input/videos/gameplay.mp4
    python scripts/transcribe.py --model small --force

Pipeline: find video(s) -> extract audio (ffmpeg) -> convert to a
whisper-compatible 16kHz mono WAV -> run local Whisper -> save a JSON
transcript (with timestamps) to processing/temp/<video-stem>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from utils import (
    FFmpegNotFoundError,
    PROCESSING_AUDIO_DIR,
    PROCESSING_TEMP_DIR,
    TranscriptionError,
    VIDEO_EXTENSIONS,
    check_ffmpeg_available,
    ensure_directories,
    INPUT_VIDEOS_DIR,
    load_config,
    run_subprocess,
    transcript_path_for_video,
)


def find_input_videos() -> list[Path]:
    """Find gameplay videos inside input/videos/, sorted for stable ordering."""
    if not INPUT_VIDEOS_DIR.exists():
        return []
    videos = [
        p for p in INPUT_VIDEOS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(videos)


def extract_audio(video_path: Path) -> Path:
    """Extract audio from video and convert to whisper-compatible 16kHz mono WAV."""
    check_ffmpeg_available()
    PROCESSING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = PROCESSING_AUDIO_DIR / f"{video_path.stem}.wav"
    args = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        str(audio_path),
    ]
    run_subprocess(args, f"Audio extraction for {video_path.name}")
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise TranscriptionError(f"Audio extraction produced no output for {video_path.name}.")
    return audio_path


def transcribe_audio(audio_path: Path, model_name: str):
    """Run local Whisper transcription. Raises TranscriptionError with a clear
    message if the whisper package is not installed or transcription fails."""
    try:
        import whisper  # type: ignore
    except ImportError as exc:
        raise TranscriptionError(
            "The 'openai-whisper' package is not installed.\n\n"
            "Install it with: pip install -r requirements.txt\n"
            "(Whisper also requires FFmpeg, which is checked separately.)"
        ) from exc

    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), verbose=False, word_timestamps=True)
    except Exception as exc:  # Whisper can raise various errors depending on backend.
        raise TranscriptionError(f"Whisper transcription failed for {audio_path.name}: {exc}") from exc
    return result


def build_transcript_json(video_path: Path, whisper_result: dict) -> dict:
    segments = []
    for seg in whisper_result.get("segments", []):
        item = {"start": round(float(seg["start"]), 2), "end": round(float(seg["end"]), 2), "text": seg["text"].strip()}
        words = []
        for word in seg.get("words", []):
            try:
                start = float(word["start"])
                end = float(word["end"])
                text = str(word.get("word", "")).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if text and start < end:
                words.append({"start": round(start, 3), "end": round(end, 3), "word": text})
        if words:
            item["words"] = words
        segments.append(item)
    return {"source": video_path.name, "segments": segments}


def transcribe_video(
    video_path: Path,
    model_name: str,
    force: bool,
    transcript_path: Path | None = None,
) -> Path:
    """Transcribe a single video end-to-end, returning the transcript JSON path."""
    transcript_path = transcript_path or transcript_path_for_video(video_path)
    if transcript_path.exists() and not force:
        print(f"  Skipping (transcript already exists): {transcript_path}")
        return transcript_path

    print(f"  Extracting audio from {video_path.name}...")
    audio_path = extract_audio(video_path)

    print(f"  Running Whisper ('{model_name}' model) on {audio_path.name}...")
    result = transcribe_audio(audio_path, model_name)

    transcript = build_transcript_json(video_path, result)
    PROCESSING_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)
    print(f"  Saved transcript: {transcript_path} ({len(transcript['segments'])} segments)")
    return transcript_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe gameplay videos using local OpenAI Whisper.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--video", type=Path, default=None,
        help="Path to a single video to transcribe. Defaults to all videos in input/videos/.",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Whisper model name (e.g. tiny, base, small, medium, large). "
             "Defaults to config/settings.json 'whisper_model'.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-transcribe even if a transcript JSON already exists.",
    )
    args = parser.parse_args(argv)

    ensure_directories()

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    model_name = args.model or config.get("whisper_model", "base")

    if args.video:
        if not args.video.exists():
            print(f"Video not found: {args.video}", file=sys.stderr)
            return 1
        videos = [args.video]
    else:
        videos = find_input_videos()
        if not videos:
            print(f"No videos found in {INPUT_VIDEOS_DIR}. Add gameplay video files and retry.")
            return 0

    print(f"Found {len(videos)} video(s) to process.")
    failures = 0
    for video in videos:
        print(f"Processing: {video.name}")
        try:
            transcribe_video(video, model_name, args.force)
        except FFmpegNotFoundError as exc:
            print(f"  {exc}", file=sys.stderr)
            failures += 1
        except TranscriptionError as exc:
            print(f"  Transcription error: {exc}", file=sys.stderr)
            failures += 1
        except RuntimeError as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"\nCompleted with {failures} failure(s).", file=sys.stderr)
        return 1
    print("\nAll transcriptions complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
