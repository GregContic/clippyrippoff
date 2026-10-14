from __future__ import annotations

import logging
import math
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.job_registry import job_registry
from backend.services.media_concurrency import run_media_task
from backend.services.project_service import (
    find_compilation as find_persisted_compilation,
    get_candidate_editor_state,
    load_candidates,
    load_project_metadata,
    project_owner_id,
    register_render_output,
    save_compilation_record,
)
from backend.services.storage import storage
from backend.services.render_service import _render_config_for, _caption_segments_for
from backend.schemas import EditingSettings
from backend.services.music_asset_service import download_project_music
from backend.services.project_service import find_music_asset, project_owner_id
from backend.services.smart_editing import apply_caption_preset, apply_smart_effects, validate_editing_timing
from scripts.make_short import build_caption_cues, render_short, write_ass_subtitles
from scripts.utils import (
    OUTPUT_SHORTS_DIR,
    PROCESSING_TEMP_DIR,
    get_media_info,
    load_config,
    load_transcript,
    run_subprocess,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_source(video_id: str, metadata: dict[str, Any]) -> Path:
    source_path = Path(str(metadata.get("source_path") or ""))
    if source_path.is_file():
        return source_path
    source_key = metadata.get("source_storage_key")
    if not isinstance(source_key, str) or not source_key:
        raise FileNotFoundError("Cached source video is missing.")
    destination = PROCESSING_TEMP_DIR / "youtube" / video_id / Path(source_key).name
    storage.download_file(source_key, destination)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise FileNotFoundError("Cached source video could not be restored from durable storage.")
    return destination


def _candidate_by_id(video_id: str, candidate_id: int) -> dict[str, Any]:
    payload = load_candidates(video_id)
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list):
        raise FileNotFoundError("No analyzed candidates are available for this project.")
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("id") == candidate_id:
            return candidate
    raise ValueError(f"Candidate {candidate_id} was not found in this project.")


def resolve_segments(
    video_id: str,
    requested_segments: list[dict[str, Any]],
    *,
    max_total_duration_seconds: float,
    source_duration_seconds: float,
    min_segment_seconds: float,
    max_segment_seconds: float,
    transition_duration_seconds: float = 0.0,
) -> tuple[list[dict[str, Any]], float]:
    """Validate and preserve submitted order; excess time can only trim the last segment."""
    if not requested_segments:
        raise ValueError("Select at least one candidate moment.")
    candidate_ids = [int(item["candidate_id"]) for item in requested_segments]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Duplicate candidate selections are not supported.")

    resolved: list[dict[str, Any]] = []
    for item in requested_segments:
        candidate_id = int(item["candidate_id"])
        candidate = _candidate_by_id(video_id, candidate_id)
        try:
            candidate_start = float(candidate["start"])
            candidate_end = float(candidate["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Candidate {candidate_id} has invalid source bounds.") from exc
        if (
            not math.isfinite(candidate_start)
            or not math.isfinite(candidate_end)
            or candidate_start < 0
            or candidate_end <= candidate_start
            or candidate_end > source_duration_seconds + 1e-6
        ):
            raise ValueError(f"Candidate {candidate_id} has bounds outside the source video.")

        editor_state = get_candidate_editor_state(video_id, candidate_id)
        saved_trim = editor_state.get("trim") if isinstance(editor_state, dict) else None
        default_start = candidate_start
        default_end = candidate_end
        if isinstance(saved_trim, dict):
            try:
                default_start = float(saved_trim.get("start", candidate_start))
                default_end = float(saved_trim.get("end", candidate_end))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Candidate {candidate_id} has an invalid saved trim.") from exc
            if (
                not math.isfinite(default_start)
                or not math.isfinite(default_end)
                or default_start < candidate_start
                or default_end > candidate_end
                or default_end <= default_start
            ):
                raise ValueError(f"Candidate {candidate_id} has an invalid saved trim.")

        start = float(item["start"]) if item.get("start") is not None else default_start
        end = float(item["end"]) if item.get("end") is not None else default_end
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError(f"Candidate {candidate_id} trim timestamps must be finite.")
        if start < candidate_start or end > candidate_end or start < 0 or end > source_duration_seconds:
            raise ValueError(f"Candidate {candidate_id} trim must stay within its candidate and source bounds.")
        duration = end - start
        if duration + 1e-6 < min_segment_seconds:
            raise ValueError(
                f"Candidate {candidate_id} is too short; each moment must be at least {min_segment_seconds:g} seconds."
            )
        if duration - 1e-6 > max_segment_seconds:
            raise ValueError(
                f"Candidate {candidate_id} is too long; each moment must be at most {max_segment_seconds:g} seconds."
            )
        resolved.append(
            {"candidate_id": candidate_id, "start": start, "end": end, "duration": duration}
        )

    overlap = transition_duration_seconds * max(0, len(resolved) - 1)
    total = sum(segment["duration"] for segment in resolved) - overlap
    if total > max_total_duration_seconds + 1e-6:
        final = resolved[-1]
        available = max_total_duration_seconds + overlap - sum(segment["duration"] for segment in resolved[:-1])
        if available + 1e-6 < min_segment_seconds:
            raise ValueError(
                "The preferred total duration cannot fit the submitted moments without making the final moment too short."
            )
        if available > max_segment_seconds + 1e-6:
            raise ValueError("The preferred total duration exceeds the maximum valid final segment length.")
        final["end"] = final["start"] + available
        final["duration"] = available
        total = sum(segment["duration"] for segment in resolved) - overlap
    if transition_duration_seconds > 0:
        for left, right in zip(resolved, resolved[1:]):
            if transition_duration_seconds >= min(left["duration"], right["duration"]):
                raise ValueError("Crossfade duration must be shorter than each adjacent segment.")
    return resolved, total


def build_concat_command(
    segment_paths: list[Path],
    output_path: Path,
    config: dict[str, Any],
    *,
    has_audio: bool,
    transition: str = "hard_cut",
    transition_duration_seconds: float = 0.5,
    segment_durations: list[float] | None = None,
) -> list[str]:
    if not segment_paths:
        raise ValueError("At least one normalized segment is required.")
    if transition not in {"hard_cut", "crossfade"}:
        raise ValueError("Unsupported compilation transition.")
    if transition == "crossfade" and len(segment_paths) > 1:
        if segment_durations is None or len(segment_durations) != len(segment_paths):
            raise ValueError("Segment durations are required to build crossfades.")
        if not math.isfinite(transition_duration_seconds) or transition_duration_seconds <= 0:
            raise ValueError("Crossfade duration must be a positive finite number.")
        return _build_crossfade_command(
            segment_paths,
            output_path,
            config,
            has_audio=has_audio,
            transition_duration_seconds=transition_duration_seconds,
            segment_durations=segment_durations,
        )
    args = ["ffmpeg", "-y"]
    for segment_path in segment_paths:
        args.extend(["-i", str(segment_path)])

    fps = float(config.get("fps", 30))
    video_labels: list[str] = []
    audio_labels: list[str] = []
    filters: list[str] = []
    for index in range(len(segment_paths)):
        video_label = f"v{index}"
        filters.append(
            f"[{index}:v:0]fps={fps:g},format=yuv420p,setsar=1[{video_label}]"
        )
        video_labels.append(f"[{video_label}]")
        if has_audio:
            audio_label = f"a{index}"
            filters.append(
                f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[{audio_label}]"
            )
            audio_labels.append(f"[{audio_label}]")
    concat_inputs = "".join(
        video_labels[index] + (audio_labels[index] if has_audio else "")
        for index in range(len(segment_paths))
    )
    audio_count = 1 if has_audio else 0
    filters.append(
        f"{concat_inputs}concat=n={len(segment_paths)}:v=1:a={audio_count}[v]"
        + ("[a]" if has_audio else "")
    )

    args.extend(["-filter_complex", ";".join(filters), "-map", "[v]"])
    if has_audio:
        args.extend(["-map", "[a]", "-c:a", str(config.get("audio_codec", "aac")),
                     "-b:a", str(config.get("audio_bitrate", "192k")), "-ar", "48000", "-ac", "2"])
    else:
        args.append("-an")
    args.extend([
        "-c:v", str(config.get("video_codec", "libx264")),
        "-preset", str(config.get("video_preset", "medium")),
        "-crf", str(config.get("video_crf", 20)),
        "-r", f"{fps:g}",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ])
    return args


def _build_crossfade_command(
    segment_paths: list[Path],
    output_path: Path,
    config: dict[str, Any],
    *,
    has_audio: bool,
    transition_duration_seconds: float,
    segment_durations: list[float],
) -> list[str]:
    args = ["ffmpeg", "-y"]
    for path in segment_paths:
        args.extend(["-i", str(path)])
    fps = float(config.get("fps", 30))
    filters: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []
    for index in range(len(segment_paths)):
        video_label = f"v{index}"
        filters.append(
            f"[{index}:v:0]fps={fps:g},format=yuv420p,setsar=1,settb=AVTB,"
            f"setpts=PTS-STARTPTS[{video_label}]"
        )
        video_labels.append(f"[{video_label}]")
        if has_audio:
            audio_label = f"a{index}"
            filters.append(
                f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:"
                f"channel_layouts=stereo,asetpts=PTS-STARTPTS[{audio_label}]"
            )
            audio_labels.append(f"[{audio_label}]")

    previous_video = video_labels[0]
    previous_audio = audio_labels[0] if has_audio else ""
    for index in range(1, len(segment_paths)):
        transition_index = index - 1
        duration = transition_duration_seconds
        offset = sum(segment_durations[:index]) - index * duration
        video_output = f"vx{transition_index}"
        filters.append(
            f"{previous_video}{video_labels[index]}xfade=transition=fade:"
            f"duration={duration:.3f}:offset={offset:.3f}[{video_output}]"
        )
        previous_video = f"[{video_output}]"
        if has_audio:
            audio_output = f"ax{transition_index}"
            filters.append(
                f"{previous_audio}{audio_labels[index]}acrossfade=d={duration:.3f}:"
                f"c1=tri:c2=tri[{audio_output}]"
            )
            previous_audio = f"[{audio_output}]"

    args.extend(["-filter_complex", ";".join(filters), "-map", previous_video])
    if has_audio:
        args.extend(["-map", previous_audio, "-c:a", str(config.get("audio_codec", "aac")),
                     "-b:a", str(config.get("audio_bitrate", "192k")), "-ar", "48000", "-ac", "2"])
    else:
        args.append("-an")
    args.extend([
        "-c:v", str(config.get("video_codec", "libx264")),
        "-preset", str(config.get("video_preset", "medium")),
        "-crf", str(config.get("video_crf", 20)),
        "-r", f"{fps:g}",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ])
    return args


def verify_compilation_output(output_path: Path, config: dict[str, Any], expected_duration: float) -> None:
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Compilation output is missing or empty.")
    info = get_media_info(output_path)
    if not info.get("has_video"):
        raise RuntimeError("Compilation output has no video stream.")
    if info.get("width") != config["output_width"] or info.get("height") != config["output_height"]:
        raise RuntimeError(
            f"Compilation output dimensions are {info.get('width')}x{info.get('height')}; "
            f"expected {config['output_width']}x{config['output_height']}."
        )
    duration = info.get("duration")
    if duration is None or not math.isfinite(float(duration)):
        raise RuntimeError("Could not determine compilation output duration.")
    if abs(float(duration) - expected_duration) > 1.5:
        raise RuntimeError(
            f"Compilation output duration is {float(duration):.2f}s; expected approximately {expected_duration:.2f}s."
        )


def _caption_source(video_id: str, captions_enabled: bool) -> list[dict[str, Any]]:
    if not captions_enabled:
        return []
    path = PROCESSING_TEMP_DIR / "youtube" / video_id / "transcript.json"
    if not path.is_file():
        raise FileNotFoundError("Cached transcript is missing; compilation captions cannot be generated.")
    transcript = load_transcript(path)
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Cached transcript does not contain valid caption segments.")
    return segments


def _compilation_view(record: dict[str, Any], job: Any | None = None) -> dict[str, Any]:
    status = job.status if job is not None else str(record.get("status", "interrupted"))
    progress = float(job.percent or 0.0) if job is not None else float(record.get("progress", 0.0))
    output_artifact_id = record.get("output_artifact_id")
    output_url = record.get("output_url")
    if job is not None and job.status == "completed":
        output_artifact_id = job.artifact_id or output_artifact_id
        output_url = job.output_url or output_url
    return {
        "compilation_id": record["compilation_id"],
        "project_id": record["project_id"],
        "parent_job_id": record["parent_job_id"],
        "status": status,
        "progress": progress,
        "segments": record["segments"],
        "effective_duration_seconds": record["effective_duration_seconds"],
        "output_artifact_id": output_artifact_id,
        "output_url": output_url,
        "message": job.message if job is not None else record.get("message"),
        "failure": job.error if job is not None else record.get("failure"),
        "created_at": record["created_at"],
        "updated_at": job.updated_at if job is not None else record.get("updated_at"),
        "completed_at": record.get("completed_at"),
    }


def create_compilation(
    video_id: str,
    *,
    owner_id: str,
    segments: list[dict[str, Any]],
    max_total_duration_seconds: float,
    render_settings: dict[str, Any] | None,
    editing: EditingSettings | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if project_owner_id(video_id) != owner_id:
        raise FileNotFoundError("Project not found.")
    metadata = load_project_metadata(video_id)
    if metadata is None:
        raise FileNotFoundError("Project not found.")
    source = _resolve_source(video_id, metadata)
    source_info = get_media_info(source)
    source_duration_value = source_info.get("duration")
    if source_duration_value is None or not math.isfinite(float(source_duration_value)):
        raise ValueError("Could not determine source video duration.")
    editing_settings = EditingSettings.model_validate(editing) if editing is not None else None
    transition = editing_settings.transition if editing_settings is not None else "hard_cut"
    transition_duration = (
        editing_settings.transition_duration_seconds
        if editing_settings is not None and transition == "crossfade"
        else 0.0
    )
    if transition == "crossfade" and len(segments) < 2:
        raise ValueError("Crossfade requires at least two compilation moments.")
    if editing_settings is not None and editing_settings.music is not None:
        if project_owner_id(video_id) != owner_id or find_music_asset(
            video_id, editing_settings.music.asset_id, owner_id=owner_id
        ) is None:
            raise ValueError("The selected project music asset was not found.")
    config = load_config()
    resolved, effective_duration = resolve_segments(
        video_id,
        segments,
        max_total_duration_seconds=max_total_duration_seconds,
        source_duration_seconds=float(source_duration_value),
        min_segment_seconds=float(config.get("clip_min_seconds", 10)),
        max_segment_seconds=float(config.get("clip_max_seconds", 60)),
        transition_duration_seconds=transition_duration,
    )
    settings = render_settings or {}
    config = apply_caption_preset(_render_config_for(config, {"render_settings": settings}), editing_settings)
    captions_enabled = bool(settings.get("captions_enabled", config.get("captions_enabled", True)))
    if editing_settings is not None:
        validate_editing_timing(editing_settings, effective_duration)
    transcript_segments = _caption_source(video_id, captions_enabled)

    compilation_id = f"compilation-{uuid.uuid4().hex}"
    artifact_id = f"artifact-{uuid.uuid4().hex}"
    filename = f"compilation_{artifact_id}.mp4"
    output_path = OUTPUT_SHORTS_DIR / filename
    output_key = f"projects/{video_id}/renders/{artifact_id}/{filename}"
    if output_path.exists() or storage.exists(output_key):
        raise RuntimeError("Compilation output identity already exists; refusing to overwrite it.")
    parent = job_registry.create(
        "compilation",
        video_id=video_id,
        stage="queued",
        message="Compilation queued.",
        result={"compilation_id": compilation_id},
        percent=0.0,
        artifact_id=artifact_id,
        artifact_kind="compilation",
    )
    record: dict[str, Any] = {
        "compilation_id": compilation_id,
        "project_id": video_id,
        "owner_id": owner_id,
        "parent_job_id": parent.id,
        "status": "queued",
        "progress": 0.0,
        "segments": resolved,
        "effective_duration_seconds": effective_duration,
        "output_artifact_id": None,
        "output_url": None,
        "message": "Compilation queued.",
        "failure": None,
        "created_at": parent.created_at,
        "updated_at": parent.updated_at,
        "completed_at": None,
        "output_filename": filename,
        "output_storage_key": output_key,
        "editing": editing_settings.model_dump() if editing_settings is not None else None,
    }
    try:
        save_compilation_record(video_id, record)
    except Exception as exc:
        try:
            job_registry.update(
                parent.id,
                status="failed",
                stage="failed",
                message="Compilation could not be persisted.",
                error=str(exc),
            )
        except Exception:
            logger.exception("Could not persist failure state for compilation job %s", parent.id)
        raise

    def _runner() -> None:
        temp_dir = PROCESSING_TEMP_DIR / "compilations" / compilation_id
        normalized_paths: list[Path] = []
        try:
            temp_dir.mkdir(parents=True, exist_ok=False)
            current = {**record, "status": "running", "message": "Preparing compilation.", "updated_at": _now()}
            save_compilation_record(video_id, current)
            job_registry.update(parent.id, status="running", stage="rendering", message="Preparing compilation.", percent=0.0)

            for index, segment in enumerate(resolved):
                ass_path: Path | None = None
                if captions_enabled:
                    candidate_state = get_candidate_editor_state(video_id, segment["candidate_id"])
                    caption_segments = _caption_segments_for(
                        candidate_state if isinstance(candidate_state, dict) else {},
                        transcript_segments,
                    )
                    cues = build_caption_cues(
                        caption_segments,
                        segment["start"],
                        segment["end"],
                        max_words_per_chunk=int(config.get("caption_max_words_per_segment", 5)),
                        max_chars_per_line=int(config.get("caption_max_chars_per_line", 18)),
                        max_lines=int(config.get("caption_max_lines", 2)),
                    )
                    if cues:
                        ass_path = temp_dir / f"segment_{index:03d}.ass"
                        write_ass_subtitles(cues, config, ass_path)
                segment_path = temp_dir / f"segment_{index:03d}.mp4"
                normalized_paths.append(segment_path)
                start_percent = index / len(resolved) * 85.0
                segment_percent = 85.0 / len(resolved)

                def on_progress(progress: dict[str, str], base: float = start_percent, span: float = segment_percent,
                                duration: float = segment["duration"]) -> None:
                    raw_time = progress.get("out_time_us") or progress.get("out_time_ms")
                    try:
                        seconds = float(raw_time) / 1_000_000 if raw_time not in (None, "N/A") else 0.0
                    except (TypeError, ValueError):
                        return
                    percent = min(85.0, base + span * max(0.0, seconds / duration))
                    job_registry.update(parent.id, percent=percent)

                render_short(
                    source,
                    segment["start"],
                    segment["end"],
                    config,
                    ass_path,
                    segment_path,
                    progress_callback=on_progress,
                )
                if not segment_path.is_file() or segment_path.stat().st_size == 0:
                    raise RuntimeError(f"Normalized segment {index + 1} is missing or empty.")
                if ass_path is not None:
                    ass_path.unlink(missing_ok=True)

            concat_command = build_concat_command(
                normalized_paths,
                output_path,
                config,
                has_audio=bool(source_info.get("has_audio")),
                transition=transition,
                transition_duration_seconds=transition_duration or 0.5,
                segment_durations=[float(segment["duration"]) for segment in resolved],
            )
            job_registry.update(parent.id, stage="concatenating", message="Joining normalized moments.", percent=88.0)
            run_subprocess(concat_command, "Compilation concatenation")
            effect_temp_dir = temp_dir / "effects"
            music_path = None
            if editing_settings is not None and editing_settings.music is not None:
                music_path = download_project_music(
                    video_id,
                    editing_settings.music.asset_id,
                    owner_id=owner_id,
                    destination_dir=effect_temp_dir,
                )
            if editing_settings is not None:
                apply_smart_effects(
                    output_path,
                    settings=editing_settings,
                    duration_seconds=effective_duration,
                    config=config,
                    has_original_audio=bool(source_info.get("has_audio")),
                    temp_dir=effect_temp_dir,
                    music_path=music_path,
                )
            verify_compilation_output(output_path, config, effective_duration)
            job_registry.update(parent.id, stage="uploading", message="Saving completed compilation.", percent=94.0)
            if storage.exists(output_key):
                raise RuntimeError("Compilation output already exists; refusing to overwrite it.")
            storage.upload_file(output_path, output_key, "video/mp4")
            register_render_output(
                video_id,
                filename,
                artifact_id=artifact_id,
                job_id=parent.id,
                storage_key=output_key,
                artifact_kind="compilation",
            )
            completed_at = _now()
            current = {
                **record,
                "status": "completed",
                "progress": 100.0,
                "output_artifact_id": artifact_id,
                "output_url": f"/api/media/artifacts/{artifact_id}",
                "message": "Compilation complete.",
                "failure": None,
                "updated_at": completed_at,
                "completed_at": completed_at,
            }
            save_compilation_record(video_id, current)
            job_registry.update(
                parent.id,
                status="completed",
                stage="complete",
                message="Compilation complete.",
                output_path=str(output_path),
                output_url=f"/api/media/artifacts/{artifact_id}",
                percent=100.0,
                result={
                    "compilation_id": compilation_id,
                    "output_storage_key": output_key,
                    "effective_duration_seconds": effective_duration,
                    "artifact_id": artifact_id,
                },
            )
        except Exception as exc:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove failed compilation output %s", output_path)
            failed_at = _now()
            failed = {
                **record,
                "status": "failed",
                "progress": float(job_registry.get(parent.id).percent or 0.0) if job_registry.get(parent.id) else 0.0,
                "message": "Compilation failed.",
                "failure": str(exc),
                "updated_at": failed_at,
                "completed_at": failed_at,
            }
            try:
                job_registry.update(
                    parent.id,
                    status="failed",
                    stage="failed",
                    message="Compilation failed.",
                    error=str(exc),
                )
            except Exception:
                logger.exception("Could not persist failed compilation job %s", parent.id)
            try:
                save_compilation_record(video_id, failed)
            except Exception:
                logger.exception("Could not persist failed compilation %s", compilation_id)
        finally:
            try:
                shutil.rmtree(temp_dir)
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("Could not remove compilation temporary files %s", temp_dir)

    thread = threading.Thread(target=run_media_task, args=(_runner,), daemon=True)
    thread.start()
    return get_compilation(compilation_id, owner_id=owner_id) or _compilation_view(record, parent)


def get_compilation(compilation_id: str, *, owner_id: str) -> dict[str, Any] | None:
    record = find_persisted_compilation(compilation_id, owner_id=owner_id)
    if record is None:
        return None
    parent_id = record.get("parent_job_id")
    job = job_registry.get(parent_id) if isinstance(parent_id, str) else None
    return _compilation_view(record, job)
