"""Detect and rank explainable gameplay clip candidates.

V2 deliberately combines simple signals instead of claiming to understand a
video: Whisper reactions, local audio RMS spikes, and lightweight frame
changes. Candidates are suggestions for human review, never publishing
recommendations or claims of virality.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from detectors.audio import AudioPeak, detect_audio_peaks, extract_mono_wav
from detectors.scenes import SceneChange, detect_scene_changes
from detectors.transcript import TranscriptTrigger, detect_transcript_triggers, transcript_signal_for_window
from transcribe import transcribe_video
from utils import (
    FFmpegNotFoundError,
    PROCESSING_TEMP_DIR,
    TranscriptionError,
    ensure_directories,
    get_media_info,
    load_config,
    load_transcript,
    transcript_path_for_video,
)
from youtube import YouTubeError, cache_paths, download_youtube_video


@dataclass
class CandidateWindow:
    start: float
    end: float
    trigger_time: float | None = None
    trigger_types: list[str] | None = None
    start_reason: str = "context"
    end_reason: str = "context"
    setup_seconds: float | None = None
    payoff_seconds: float | None = None


def candidates_path_for_video(video_path: Path) -> Path:
    return PROCESSING_TEMP_DIR / f"{video_path.stem}_candidates.json"


def _overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    return start <= other_end and other_start <= end


def _reaction_strength(triggers: list[TranscriptTrigger]) -> str:
    strengths = [getattr(trigger, "strength", "medium") for trigger in triggers]
    return max(
        strengths or ["medium"],
        key=lambda strength: {"weak": 0, "medium": 1, "strong": 2}.get(strength, 1),
    )


def _boundary_context_seconds(before_seconds: float, after_seconds: float, strength: str) -> tuple[float, float]:
    factor = {"weak": 0.6, "medium": 0.85, "strong": 1.0}.get(strength, 0.85)
    return before_seconds * factor, after_seconds * factor


def _expand_to_minimum(
    start: float,
    end: float,
    trigger_time: float,
    video_duration: float,
    min_seconds: float,
) -> tuple[float, float]:
    duration = end - start
    if duration >= min_seconds:
        return start, end
    missing = min_seconds - duration
    start = max(0.0, start - missing / 2)
    end = min(video_duration, end + missing / 2)
    if end - start < min_seconds:
        if start == 0.0:
            end = min(video_duration, min_seconds)
        elif end == video_duration:
            start = max(0.0, video_duration - min_seconds)
        else:
            start = max(0.0, trigger_time - min_seconds / 2)
            end = min(video_duration, start + min_seconds)
            start = max(0.0, end - min_seconds)
    return start, end


def _limit_window(
    start: float,
    end: float,
    trigger_time: float,
    video_duration: float,
    max_seconds: float,
) -> tuple[float, float]:
    if end - start <= max_seconds:
        return start, end
    start = max(0.0, trigger_time - max_seconds / 2)
    end = min(video_duration, start + max_seconds)
    return max(0.0, end - max_seconds), end


def build_candidate_windows(
    triggers: list[TranscriptTrigger],
    audio_peaks: list[AudioPeak],
    scene_changes: list[SceneChange],
    video_duration: float,
    min_seconds: float,
    max_seconds: float,
    before_seconds: float,
    after_seconds: float,
    merge_gap_seconds: float,
    transcript_segments: list[dict] | None = None,
    continuation_gap_seconds: float = 1.5,
    quiet_boundary_seconds: float = 1.5,
    scene_transition_threshold: float = 0.28,
) -> list[CandidateWindow]:
    """Cluster signals and choose deterministic, event-aware clip boundaries."""
    events = [(item.start, item.end, "reaction", getattr(item, "score", 0.0)) for item in triggers]
    events.extend((item.start, item.end, "audio_peak", getattr(item, "relative_peak", 0.0)) for item in audio_peaks)
    events.extend((item.start, item.end, "scene_change", getattr(item, "change_score", 0.0)) for item in scene_changes)
    if not events:
        return []

    clusters: list[list[tuple[float, float, str, float]]] = []
    for event in sorted(events):
        if clusters and event[0] <= max(item[1] for item in clusters[-1]) + merge_gap_seconds:
            clusters[-1].append(event)
        else:
            clusters.append([event])

    segment_data = []
    for segment in transcript_segments or []:
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            segment_data.append({"start": start, "end": end, "text": str(segment.get("text", ""))})
    segment_data.sort(key=lambda item: item["start"])

    windows: list[CandidateWindow] = []
    for cluster in clusters:
        event_start = min(item[0] for item in cluster)
        event_end = max(item[1] for item in cluster)
        weights = [max(float(item[3]), 0.01) for item in cluster]
        trigger_time = sum(((item[0] + item[1]) / 2) * weight for item, weight in zip(cluster, weights)) / sum(weights)
        trigger_types = sorted({item[2] for item in cluster})
        cluster_triggers = [item for item in triggers if _overlaps(item.start, item.end, event_start, event_end)]
        trigger_event_end = max((item.end for item in cluster_triggers), default=event_end)
        cluster_has_payoff = any(item[0] > trigger_event_end for item in cluster if item[2] != "reaction")
        before_context, after_context = _boundary_context_seconds(
            before_seconds, after_seconds, _reaction_strength(cluster_triggers)
        )
        lower_bound = max(0.0, trigger_time - before_seconds)
        start = max(0.0, trigger_time - before_context)
        end = min(video_duration, event_end + after_context)
        start_reason = "trigger_context"
        end_reason = "trigger_context"

        containing_start = next((item for item in segment_data if item["start"] <= trigger_time < item["end"]), None)
        if containing_start and containing_start["start"] >= lower_bound:
            start = containing_start["start"]
            start_reason = "sentence_start"
            current_index = segment_data.index(containing_start)
            while current_index > 0:
                previous = segment_data[current_index - 1]
                if containing_start["start"] - previous["end"] > continuation_gap_seconds or previous["end"] < lower_bound:
                    break
                start = previous["start"]
                start_reason = "setup_speech"
                containing_start = previous
                current_index -= 1

        containing_end = next((item for item in segment_data if item["start"] < event_end <= item["end"]), None)
        continued_payoff = False
        payoff_end = trigger_event_end
        if containing_end:
            end = containing_end["end"]
            payoff_end = containing_end["end"]
            end_reason = "sentence_end"
            current_index = segment_data.index(containing_end)
            payoff_segments = 0
            while current_index + 1 < len(segment_data):
                following = segment_data[current_index + 1]
                if following["start"] - segment_data[current_index]["end"] > continuation_gap_seconds:
                    break
                following_has_trigger = any(
                    trigger.start < following["end"] and trigger.end > following["start"]
                    for trigger in triggers
                )
                if payoff_segments >= 1 and not following_has_trigger:
                    break
                end = max(end, following["end"])
                end_reason = "payoff_speech"
                continued_payoff = True
                payoff_end = following["end"]
                payoff_segments += 1
                current_index += 1

        if not containing_end:
            payoff_segments_data = [item for item in segment_data if trigger_event_end <= item["end"] <= event_end]
            if payoff_segments_data:
                payoff_end = max(item["end"] for item in payoff_segments_data)

        transition = None
        for change in sorted(scene_changes, key=lambda item: item.start):
            if change.change_score < scene_transition_threshold or change.start < trigger_time or change.start > end:
                continue
            if any(
                trigger.start >= change.start
                and trigger.start <= change.end + continuation_gap_seconds
                for trigger in triggers
            ):
                continue
            if containing_end and containing_end["start"] < change.start < containing_end["end"]:
                continue
            prior_trigger_ends = [trigger.end for trigger in cluster_triggers if trigger.end <= change.start]
            prior_segment_ends = [item["end"] for item in segment_data if item["end"] <= change.start]
            change_payoff_end = max(prior_trigger_ends + prior_segment_ends, default=payoff_end)
            if change_payoff_end > change.start:
                continue
            transition = change
            break
        if transition:
            end = min(end, transition.start + quiet_boundary_seconds / 2)
            end_reason = "scene_transition_after_payoff"

        related_after = [item for item in cluster if item[0] >= event_end and item[0] <= event_end + after_seconds]
        if related_after:
            end = max(end, max(item[1] for item in related_after) + after_context)
            end_reason = "payoff_activity"
        if containing_end and not continued_payoff and not related_after and not cluster_has_payoff:
            end = min(end, containing_end["end"] + quiet_boundary_seconds)
            end_reason = "quiet_boundary"
        elif not containing_end and not related_after and not cluster_has_payoff:
            end = min(end, event_end + min(after_context, quiet_boundary_seconds))
            end_reason = "quiet_boundary"
        if not containing_start:
            start = max(start, trigger_time - before_context)
            start_reason = "quiet_boundary"

        start, end = _expand_to_minimum(start, end, trigger_time, video_duration, min_seconds)
        start, end = _limit_window(start, end, trigger_time, video_duration, max_seconds)
        if min_seconds <= end - start <= max_seconds:
            windows.append(
                CandidateWindow(
                    start, end, trigger_time, trigger_types, start_reason, end_reason,
                    max(0.0, trigger_time - start), max(0.0, end - trigger_time),
                )
            )
    return windows


def _audio_signal(peaks: list[AudioPeak], start: float, end: float) -> tuple[float, float, str]:
    overlapping = [peak for peak in peaks if _overlaps(start, end, peak.start, peak.end)]
    if not overlapping:
        return 0.0, 0.0, "NONE"
    peak = max(overlapping, key=lambda item: item.relative_peak)
    score = min(1.0, peak.relative_peak / 4.0)
    level = "HIGH" if peak.relative_peak >= 3 else "MEDIUM" if peak.relative_peak >= 2 else "LOW"
    return score, peak.relative_peak, level


def _scene_signal(changes: list[SceneChange], start: float, end: float) -> tuple[float, float]:
    overlapping = [change for change in changes if _overlaps(start, end, change.start, change.end)]
    if not overlapping:
        return 0.0, 0.0
    score = max(change.change_score for change in overlapping)
    return min(1.0, score), score


def score_candidate(
    window: CandidateWindow,
    transcript_triggers: list[TranscriptTrigger],
    audio_peaks: list[AudioPeak],
    scene_changes: list[SceneChange],
    reaction_scores: dict[str, int] | None = None,
) -> dict:
    transcript, transcript_strength, keywords = transcript_signal_for_window(
        transcript_triggers, window.start, window.end
    )
    audio_strength, relative_peak, audio_level = _audio_signal(audio_peaks, window.start, window.end)
    scene_strength, change_score = _scene_signal(scene_changes, window.start, window.end)
    reaction_scores = reaction_scores or {"weak": 3, "medium": 8, "strong": 15}
    overlapping_triggers = [trigger for trigger in transcript_triggers if _overlaps(window.start, window.end, trigger.start, trigger.end)]
    reaction_detected = bool(keywords)
    reaction_score = max((reaction_scores.get(getattr(trigger, "strength", "strong"), 0) for trigger in overlapping_triggers), default=0)
    trigger_types = set(window.trigger_types or [])
    if reaction_detected:
        trigger_types.add("reaction")
    if audio_strength:
        trigger_types.add("audio_peak")
    if scene_strength:
        trigger_types.add("scene_change")

    signals = {
        "transcript_score": round(transcript_strength * 30),
        "audio_score": round(audio_strength * 30),
        "scene_score": round(scene_strength * 15),
        "reaction_score": reaction_score,
    }
    candidate_score = min(100, sum(signals.values()))
    return {
        "start": round(window.start, 2),
        "end": round(window.end, 2),
        "duration": round(window.end - window.start, 2),
        "candidate_score": candidate_score,
        "transcript": transcript,
        "signals": signals,
        "audio_peak": round(max((peak.peak for peak in audio_peaks if _overlaps(window.start, window.end, peak.start, peak.end)), default=0.0), 3),
        "relative_audio_peak": round(relative_peak, 3),
        "audio_level": audio_level,
        "reaction_detected": reaction_detected,
        "matched_keywords": keywords,
        "scene_change_score": round(change_score, 3),
        "trigger_time": round(window.trigger_time, 2) if window.trigger_time is not None else None,
        "trigger_types": sorted(trigger_types),
        "start_reason": window.start_reason,
        "end_reason": window.end_reason,
        "setup_seconds": round(window.setup_seconds, 2) if window.setup_seconds is not None else None,
        "payoff_seconds": round(window.payoff_seconds, 2) if window.payoff_seconds is not None else None,
    }


def _select_non_overlapping(candidates: list[dict]) -> list[dict]:
    selected: list[dict] = []
    for candidate in candidates:
        if any(_overlaps(candidate["start"], candidate["end"], item["start"], item["end"]) for item in selected):
            continue
        selected.append(candidate)
    return selected


def detect_candidates(video_path: Path, config: dict, transcript_path: Path | None = None) -> list[dict]:
    """Run all V2 detectors and return ranked candidate metadata."""
    info = get_media_info(video_path)
    if not info["has_video"] or not info["has_audio"]:
        raise ValueError("Clip detection requires both video and audio streams.")
    if info["duration"] is None:
        raise ValueError("Could not determine source video duration.")

    transcript_path = transcript_path or transcript_path_for_video(video_path)
    if not transcript_path.exists():
        print(f"Transcript not found; transcribing {video_path.name} first...")
        transcribe_video(
            video_path,
            config.get("whisper_model", "base"),
            force=False,
            transcript_path=transcript_path,
        )
    transcript_data = load_transcript(transcript_path)
    reaction_keywords = config.get("reaction_keywords", [])
    reaction_scores = config.get("reaction_strength_scores", {"weak": 3, "medium": 8, "strong": 15})
    transcript_triggers = detect_transcript_triggers(
        transcript_data["segments"], reaction_keywords,
        {strength: score / 15 for strength, score in reaction_scores.items()},
    )

    audio_path = extract_mono_wav(video_path, int(config.get("audio_sample_rate", 16000)))
    audio_peaks = detect_audio_peaks(
        audio_path,
        window_seconds=float(config.get("audio_window_seconds", 0.25)),
        baseline_seconds=float(config.get("audio_baseline_seconds", 8)),
        relative_threshold=float(config.get("audio_spike_threshold", 1.8)),
        min_peak=float(config.get("audio_min_peak", 0.08)),
    )
    scene_changes = detect_scene_changes(
        video_path,
        sample_fps=float(config.get("scene_sample_fps", 1)),
        threshold=float(config.get("scene_change_threshold", 0.18)),
        max_width=int(config.get("scene_max_width", 320)),
    )
    windows = build_candidate_windows(
        transcript_triggers, audio_peaks, scene_changes, float(info["duration"]),
        float(config["clip_min_seconds"]), float(config["clip_max_seconds"]),
        float(config.get("context_before_seconds", config.get("candidate_window_before_seconds", 5))),
        float(config.get("context_after_seconds", config.get("candidate_window_after_seconds", 8))),
        float(config.get("candidate_merge_gap_seconds", 3)),
        transcript_data["segments"],
        float(config.get("boundary_continuation_gap_seconds", 1.5)),
        float(config.get("boundary_quiet_seconds", 1.5)),
        float(config.get("boundary_scene_transition_threshold", 0.28)),
    )
    candidates = [score_candidate(window, transcript_triggers, audio_peaks, scene_changes, reaction_scores) for window in windows]
    candidates.sort(key=lambda item: (-item["candidate_score"], item["start"]))
    candidates = _select_non_overlapping(candidates)
    limit = int(config.get("max_candidates", 20))
    for index, candidate in enumerate(candidates[:limit], start=1):
        candidate["id"] = index
    return candidates[:limit]


def _format_clock(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def print_candidates(candidates: list[dict]) -> None:
    print("=" * 60)
    print("                 CANDIDATE CLIPS")
    print("=" * 60)
    if not candidates:
        print("\nNo candidate moments were found with the current thresholds.")
        return
    for candidate in candidates:
        print(f"\n[{candidate['id']}] {_format_clock(candidate['start'])} → {_format_clock(candidate['end'])}")
        print(f"    Score: {candidate['candidate_score']}")
        print(f"    Duration: {candidate['duration']:.1f}s")
        print(f"    Transcript: \"{candidate['transcript'] or '(none)'}\"")
        print(f"    Audio peak: {candidate['audio_level']}")
        print(f"    Reaction detected: {'YES' if candidate['reaction_detected'] else 'NO'}")
        print(f"    Signals: {candidate['signals']}")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze a gameplay video and rank explainable candidate moments for human review.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video", type=Path, default=None, help="Path to the gameplay video.")
    parser.add_argument("--url", type=str, default=None, help="Public YouTube URL to download and analyze.")
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=None,
        help="Maximum ranked candidates to display and save (defaults to max_candidates in the config).",
    )
    parser.add_argument("--force-download", action="store_true", help="Redownload a YouTube source even when cached.")
    parser.add_argument("--transcript", type=Path, default=None, help="Optional transcript JSON override.")
    parser.add_argument("--config", type=Path, default=None, help="Optional settings.json override.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_directories()
    if args.video is not None and args.url is not None:
        print("ERROR: Provide either --video or --url, not both.", file=sys.stderr)
        return 2
    if args.video is None and args.url is None:
        print("ERROR: Provide --video or --url.", file=sys.stderr)
        return 2

    source_metadata = {"source_type": "local"}
    video_path = args.video
    transcript_path = args.transcript
    output_path = None
    if args.url is not None:
        try:
            downloaded = download_youtube_video(args.url, force_download=args.force_download)
        except YouTubeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        video_path = Path(downloaded["filepath"])
        paths = cache_paths(downloaded["video_id"])
        transcript_path = transcript_path or paths["transcript"]
        output_path = paths["candidates"]
        source_metadata = {
            "source_type": "youtube",
            "source_url": downloaded["url"],
            "video_id": downloaded["video_id"],
            "title": downloaded["title"],
        }

    if video_path is None or not video_path.exists():
        print(f"Video not found: {video_path}", file=sys.stderr)
        return 1
    try:
        config = load_config(args.config)
        candidates = detect_candidates(video_path, config, transcript_path)
        limit = args.top if args.top is not None else int(config.get("max_candidates", 20))
        candidates = candidates[:limit]
        output_path = output_path or candidates_path_for_video(video_path)
        payload = {"source": video_path.name, **source_metadata, "candidates": candidates}
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print_candidates(candidates)
        print(f"\nSaved candidate data to: {output_path}")
        return 0
    except (FFmpegNotFoundError, TranscriptionError, RuntimeError, ValueError, OSError) as exc:
        print(f"Clip detection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
