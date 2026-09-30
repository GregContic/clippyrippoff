"""Generate a single 1080x1920 YouTube Short from a gameplay video clip.

Usage:
    python scripts/make_short.py --video input/videos/gameplay.mp4 --start 32 --end 47
    python scripts/make_short.py --video input/videos/gameplay.mp4 --start 1:12 --end 1:47 --no-captions

Pipeline: validate input -> trim clip -> center-crop to vertical -> scale to
target resolution -> (optionally) burn Whisper-derived captions -> normalize
audio -> export to output/shorts/ -> verify the rendered file.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from utils import (
    FFmpegNotFoundError,
    OUTPUT_SHORTS_DIR,
    PROCESSING_TEMP_DIR,
    ValidationError,
    check_ffmpeg_available,
    ensure_directories,
    generate_output_filename,
    get_media_info,
    load_config,
    load_transcript,
    parse_timestamp,
    run_subprocess,
    run_subprocess_with_progress,
    transcript_path_for_video,
    validate_clip_range,
)

SAFE_MARGIN_PX = 60  # left/right safe margin for captions, in output pixels


# --------------------------------------------------------------------------
# Vertical crop (V1: reliable center crop; V2 can swap this out for
# subject/camera tracking while keeping the same function signature).
# --------------------------------------------------------------------------
@dataclass
class CropRect:
    width: int
    height: int
    x: int
    y: int


def compute_center_crop(src_width: int, src_height: int, target_width: int, target_height: int) -> CropRect:
    """Compute a center crop rectangle that matches the target aspect ratio.

    Never stretches the video: crops away excess width or height so the
    remaining region already has the target aspect ratio, then the caller
    scales it to the exact output resolution.
    """
    target_aspect = target_width / target_height
    src_aspect = src_width / src_height

    if src_aspect > target_aspect:
        # Source is relatively wider than target -> crop the sides.
        crop_h = src_height
        crop_w = round(src_height * target_aspect)
    else:
        # Source is relatively taller/narrower than target -> crop top/bottom.
        crop_w = src_width
        crop_h = round(src_width / target_aspect)

    crop_w = min(crop_w, src_width)
    crop_h = min(crop_h, src_height)
    x = (src_width - crop_w) // 2
    y = (src_height - crop_h) // 2
    return CropRect(width=crop_w, height=crop_h, x=x, y=y)


def build_video_filter_chain(crop: CropRect, target_width: int, target_height: int, ass_path: Path | None) -> str:
    filters = [
        f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y}",
        f"scale={target_width}:{target_height}",
        "setsar=1",
    ]
    if ass_path is not None:
        filters.append(f"subtitles='{escape_ffmpeg_path(ass_path)}'")
    return ",".join(filters)


def escape_ffmpeg_path(path: Path) -> str:
    """Escape a filesystem path for safe use inside an ffmpeg filtergraph string."""
    p = str(path.resolve()).replace("\\", "/")
    p = p.replace(":", r"\:")
    p = p.replace("'", r"\'")
    return p


# --------------------------------------------------------------------------
# Captions
# --------------------------------------------------------------------------
@dataclass
class CaptionWord:
    start: float
    end: float
    text: str


@dataclass
class CaptionCue:
    start: float
    end: float
    lines: list[str]
    words: list[CaptionWord] = field(default_factory=list)


def _wrap_words(words: list[str], max_chars_per_line: int, max_lines: int) -> list[str]:
    """Greedily wrap words into up to max_lines lines of max_chars_per_line."""
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and len(candidate) > max_chars_per_line:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    if len(lines) > max_lines:
        # Merge overflow lines into the last allowed line rather than dropping text.
        head, tail = lines[:max_lines - 1], lines[max_lines - 1:]
        lines = head + [" ".join(tail)]
    return lines


def build_caption_cues(
    segments: list[dict],
    clip_start: float,
    clip_end: float,
    max_words_per_chunk: int,
    max_chars_per_line: int,
    max_lines: int,
) -> list[CaptionCue]:
    """Convert Whisper segments overlapping [clip_start, clip_end] into short,
    readable caption cues with times relative to the clip start."""
    cues: list[CaptionCue] = []
    for seg in segments:
        seg_start, seg_end = float(seg["start"]), float(seg["end"])
        if seg_end <= clip_start or seg_start >= clip_end:
            continue  # segment doesn't overlap the clip window

        seg_start = max(seg_start, clip_start)
        seg_end = min(seg_end, clip_end)
        words = seg["text"].strip().split()
        if not words:
            continue

        timed_words: list[CaptionWord] = []
        raw_words = seg.get("words")
        if isinstance(raw_words, list) and len(raw_words) == len(words):
            parsed_words: list[CaptionWord] = []
            for raw_word in raw_words:
                try:
                    word_start = float(raw_word["start"])
                    word_end = float(raw_word["end"])
                    word_text = str(raw_word.get("word", "")).strip()
                except (KeyError, TypeError, ValueError):
                    parsed_words = []
                    break
                if not word_text or not math.isfinite(word_start) or not math.isfinite(word_end) or word_end <= word_start:
                    parsed_words = []
                    break
                parsed_words.append(CaptionWord(start=max(word_start, clip_start), end=min(word_end, clip_end), text=word_text))
            if parsed_words and all(word.end > word.start for word in parsed_words):
                timed_words = parsed_words

        chunks = [words[i:i + max_words_per_chunk] for i in range(0, len(words), max_words_per_chunk)]
        seg_duration = max(seg_end - seg_start, 0.01)
        chunk_duration = seg_duration / len(chunks)

        for i, chunk in enumerate(chunks):
            chunk_start = seg_start + i * chunk_duration - clip_start
            chunk_end = seg_start + (i + 1) * chunk_duration - clip_start
            lines = _wrap_words(chunk, max_chars_per_line, max_lines)
            chunk_words = []
            if timed_words:
                word_offset = i * max_words_per_chunk
                chunk_words = [CaptionWord(max(word.start - clip_start, 0.0), max(word.end - clip_start, 0.0), word.text) for word in timed_words[word_offset:word_offset + len(chunk)]]
            cues.append(CaptionCue(start=max(chunk_start, 0.0), end=chunk_end, lines=lines, words=chunk_words))
    return cues


def _format_ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centiseconds = round((secs - int(secs)) * 100)
    if centiseconds == 100:
        centiseconds = 0
        secs += 1
    return f"{hours:d}:{minutes:02d}:{int(secs):02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _ass_word_duration(seconds: float) -> int:
    return max(1, round(seconds * 100))


def _pop_events(cue: CaptionCue, config: dict) -> list[str]:
    if not cue.words:
        text = r"\N".join(_escape_ass_text(line) for line in cue.lines)
        return [f"Dialogue: 0,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},Default,,0,0,0,,{{\\fad(120,80)}}{text}\n"]
    text_words = [word.text for word in cue.words]
    events: list[str] = []
    for index, word in enumerate(cue.words):
        prefix = " ".join(text_words[:index])
        current = _escape_ass_text(text_words[index])
        suffix = " ".join(text_words[index + 1:])
        text = " ".join(part for part in (prefix, f"{{\\fscx80\\fscy80\\t(0,{round(config.get('caption_animation_duration', 0.16) * 1000)},\\fscx100\\fscy100)}}{current}", suffix) if part)
        events.append(f"Dialogue: 0,{_format_ass_time(word.start)},{_format_ass_time(cue.end)},Default,,0,0,0,,{text}\n")
    return events


def _animated_events(cue: CaptionCue, config: dict) -> list[str]:
    animation = config.get("caption_animation", "none")
    text = r"\N".join(_escape_ass_text(line) for line in cue.lines)
    if animation == "fade":
        return [f"Dialogue: 0,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},Default,,0,0,0,,{{\\fad(160,100)}}{text}\n"]
    if animation == "karaoke" and cue.words:
        karaoke = " ".join(f"{{\\k{_ass_word_duration(word.end - word.start)}}}{_escape_ass_text(word.text)}" for word in cue.words)
        return [f"Dialogue: 0,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},Default,,0,0,0,,{{\\2c{config.get('caption_highlight_color', '&H0000FFFF')}}}{karaoke}\n"]
    if animation == "pop":
        return _pop_events(cue, config)
    return [f"Dialogue: 0,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},Default,,0,0,0,,{text}\n"]


def write_ass_subtitles(cues: list[CaptionCue], config: dict, ass_path: Path) -> None:
    """Write cues as an .ass subtitle file styled per config, ready to burn in with ffmpeg."""
    out_w = config["output_width"]
    out_h = config["output_height"]
    margin_v = round(config.get("caption_vertical_margin_percent", 0.3) * out_h)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {out_w}
PlayResY: {out_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.get("caption_font_name", "Arial Black")},{config.get("caption_font_size", 72)},{config.get("caption_primary_color", "&H00FFFFFF")},&H000000FF,{config.get("caption_outline_color", "&H00000000")},{config.get("caption_shadow_color", "&H80000000")},{-1 if config.get("caption_bold", True) else 0},0,0,0,100,100,0,0,1,{config.get("caption_outline_width", 4)},{config.get("caption_shadow_depth", 3)},2,{SAFE_MARGIN_PX},{SAFE_MARGIN_PX},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        if cue.end <= cue.start:
            continue
        lines.extend(_animated_events(cue, config))

    try:
        ass_path.parent.mkdir(parents=True, exist_ok=True)
        ass_path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not write subtitle file to {ass_path}: {exc}") from exc


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def render_short(
    video_path: Path,
    start: float,
    end: float,
    config: dict,
    ass_path: Path | None,
    output_path: Path,
    progress_callback: Callable[[dict[str, str]], None] | None = None,
) -> None:
    check_ffmpeg_available()
    info = get_media_info(video_path)
    if not info["has_video"]:
        raise ValidationError(f"No video stream found in {video_path.name}.")

    crop = compute_center_crop(info["width"], info["height"], config["output_width"], config["output_height"])
    vf = build_video_filter_chain(crop, config["output_width"], config["output_height"], ass_path)

    duration = end - start
    args = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(video_path),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-r", str(config.get("fps", 30)),
        "-c:v", config.get("video_codec", "libx264"),
        "-preset", config.get("video_preset", "medium"),
        "-crf", str(config.get("video_crf", 20)),
        "-pix_fmt", "yuv420p",
    ]

    if info["has_audio"]:
        af = "loudnorm=I=-16:TP=-1.5:LRA=11" if config.get("normalize_audio", True) else None
        if af:
            args += ["-af", af]
        args += ["-c:a", config.get("audio_codec", "aac"), "-b:a", config.get("audio_bitrate", "192k")]
    else:
        args += ["-an"]

    if progress_callback is not None:
        args += ["-progress", "pipe:1", "-nostats"]
    args += ["-movflags", "+faststart", str(output_path)]

    if progress_callback is not None:
        run_subprocess_with_progress(args, "Short rendering", progress_callback)
    else:
        run_subprocess(args, "Short rendering")


def verify_output(output_path: Path, config: dict, expected_duration: float) -> list[str]:
    """Verify the rendered Short. Returns a list of problems (empty = OK)."""
    problems: list[str] = []
    if not output_path.exists():
        return [f"Output file does not exist: {output_path}"]
    if output_path.stat().st_size == 0:
        problems.append("Output file is empty (0 bytes).")
        return problems

    try:
        info = get_media_info(output_path)
    except Exception as exc:
        return [f"Could not inspect output file with ffprobe: {exc}"]

    if not info["has_video"]:
        problems.append("Output file has no video stream.")
    if not info["has_audio"]:
        problems.append("Output file has no audio stream.")
    if info["width"] != config["output_width"] or info["height"] != config["output_height"]:
        problems.append(
            f"Output resolution is {info['width']}x{info['height']}, "
            f"expected {config['output_width']}x{config['output_height']}."
        )
    if info["duration"] is None:
        problems.append("Could not determine output duration.")
    else:
        tolerance = 1.5  # seconds, to allow for encoder/keyframe rounding
        if abs(info["duration"] - expected_duration) > tolerance:
            problems.append(
                f"Output duration is {info['duration']:.2f}s, expected ~{expected_duration:.2f}s."
            )
    return problems


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Turn a section of a gameplay video into a 1080x1920 YouTube Short with burned-in captions.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/make_short.py --video input/videos/gameplay.mp4 --start 32 --end 47\n"
            "  python scripts/make_short.py --video input/videos/gameplay.mp4 --start 1:12 --end 1:47\n"
            "  python scripts/make_short.py --video input/videos/gameplay.mp4 --start 32 --end 47 --no-captions"
        ),
    )
    parser.add_argument("--video", type=Path, required=True, help="Path to the source gameplay video.")
    parser.add_argument("--start", type=str, required=True, help="Clip start timestamp (seconds or HH:MM:SS).")
    parser.add_argument("--end", type=str, required=True, help="Clip end timestamp (seconds or HH:MM:SS).")
    parser.add_argument("--transcript", type=Path, default=None, help="Path to a transcript JSON (defaults to processing/temp/<video-stem>.json).")
    parser.add_argument("--no-captions", action="store_true", help="Skip caption generation and burn-in.")
    parser.add_argument("--config", type=Path, default=None, help="Path to an alternate settings.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    ensure_directories()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if not args.video.exists():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1

    try:
        start = parse_timestamp(args.start)
        end = parse_timestamp(args.end)
    except ValidationError as exc:
        print(f"Invalid timestamp: {exc}", file=sys.stderr)
        return 1

    try:
        check_ffmpeg_available()
        info = get_media_info(args.video)
    except FFmpegNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Could not inspect video: {exc}", file=sys.stderr)
        return 1

    try:
        validate_clip_range(
            start, end,
            config["clip_min_seconds"], config["clip_max_seconds"],
            video_duration=info["duration"],
        )
    except ValidationError as exc:
        print(f"Invalid clip range: {exc}", file=sys.stderr)
        return 1

    if not info["has_audio"]:
        print(f"Error: {args.video.name} has no audio stream. Cannot preserve gameplay audio.", file=sys.stderr)
        return 1

    # Captions
    ass_path: Path | None = None
    if not args.no_captions:
        transcript_path = args.transcript or transcript_path_for_video(args.video)
        if not transcript_path.exists():
            print(
                f"No transcript found at {transcript_path}.\n"
                f"Run 'python scripts/transcribe.py --video {args.video}' first, "
                "or pass --no-captions to render without captions.",
                file=sys.stderr,
            )
            return 1
        try:
            transcript = load_transcript(transcript_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Transcript error: {exc}", file=sys.stderr)
            return 1

        cues = build_caption_cues(
            transcript["segments"], start, end,
            max_words_per_chunk=config.get("caption_max_words_per_segment", 5),
            max_chars_per_line=config.get("caption_max_chars_per_line", 18),
            max_lines=config.get("caption_max_lines", 2),
        )
        if cues:
            ass_path = PROCESSING_TEMP_DIR / f"{args.video.stem}_{int(start)}_{int(end)}.ass"
            try:
                write_ass_subtitles(cues, config, ass_path)
            except RuntimeError as exc:
                print(f"Caption error: {exc}", file=sys.stderr)
                return 1
        else:
            print("Note: no transcript segments overlap this clip range; rendering without captions.")

    output_path = generate_output_filename(OUTPUT_SHORTS_DIR)
    print(f"Rendering short from {args.video.name} [{start:.2f}s -> {end:.2f}s] to {output_path.name}...")

    try:
        render_short(args.video, start, end, config, ass_path, output_path)
    except (FFmpegNotFoundError, RuntimeError, ValidationError) as exc:
        print(f"Rendering failed: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Filesystem error while rendering: {exc}", file=sys.stderr)
        return 1

    problems = verify_output(output_path, config, expected_duration=end - start)
    if problems:
        print("Verification FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"Success: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
