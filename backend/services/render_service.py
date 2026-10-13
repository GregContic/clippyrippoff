from __future__ import annotations

import math
import shutil
import threading
import uuid
from pathlib import Path

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.services.job_registry import job_registry
from backend.services.project_service import (
    get_candidate_editor_state,
    load_candidates,
    load_project_metadata,
    patch_project_metadata,
    register_render_output,
    save_project_metadata,
)
from scripts.make_short import build_caption_cues, render_short, verify_output, write_ass_subtitles
from scripts.utils import (
    OUTPUT_SHORTS_DIR,
    PROCESSING_TEMP_DIR,
    ValidationError as ClipValidationError,
    generate_output_filename,
    get_media_info,
    load_config,
    load_transcript,
    validate_clip_range,
)
from backend.services.storage import storage
from backend.schemas import EditingSettings
from backend.services.music_asset_service import download_project_music
from backend.services.project_service import find_music_asset, project_owner_id
from backend.services.smart_editing import apply_caption_preset, apply_smart_effects, validate_editing_timing


class TrimValidationError(ValueError):
    pass


def _candidate_map(video_id: str) -> dict[int, dict]:
    payload = load_candidates(video_id)
    if not payload:
        return {}
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return {}
    mapped: dict[int, dict] = {}
    for candidate in candidates:
        try:
            mapped[int(candidate["id"])] = candidate
        except (KeyError, TypeError, ValueError):
            continue
    return mapped


def validate_candidate_ids(video_id: str, candidate_ids: list[int]) -> dict[int, dict]:
    if not candidate_ids:
        raise ValueError("Select at least one candidate to render.")
    candidates = _candidate_map(video_id)
    if not candidates:
        raise FileNotFoundError("No candidates are available for this video yet.")
    missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in candidates]
    if missing:
        raise KeyError(f"Candidate(s) not found: {', '.join(str(candidate_id) for candidate_id in missing)}")
    return {candidate_id: candidates[candidate_id] for candidate_id in candidate_ids}


def _selected_bounds(candidate: dict, override: object | None) -> tuple[float, float]:
    if override is None:
        start = float(candidate["start"])
        end = float(candidate["end"])
    elif isinstance(override, dict):
        start = float(override.get("start"))
        end = float(override.get("end"))
    else:
        start = float(getattr(override, "start"))
        end = float(getattr(override, "end"))
    if not math.isfinite(start) or not math.isfinite(end):
        raise TrimValidationError("Trim timestamps must be finite numbers.")
    return start, end


def _validate_bounds(start: float, end: float, *, min_seconds: float, max_seconds: float, source_duration: float | None) -> None:
    try:
        validate_clip_range(start, end, min_seconds=min_seconds, max_seconds=max_seconds, video_duration=source_duration)
    except ClipValidationError as exc:
        raise TrimValidationError(str(exc)) from exc


def _candidate_state_for(video_id: str, candidate_id: int, request_state: object | None) -> dict:
    if isinstance(request_state, dict):
        return request_state
    state = get_candidate_editor_state(video_id, candidate_id)
    return state if isinstance(state, dict) else {}


def _render_config_for(base_config: dict, candidate_state: dict) -> dict:
    render_settings = candidate_state.get("render_settings", {})
    if not isinstance(render_settings, dict):
        render_settings = {}
    merged = dict(base_config)
    for key in ("output_width", "output_height", "fps", "normalize_audio", "caption_font_name", "caption_font_size", "caption_primary_color", "caption_outline_color", "caption_shadow_color", "caption_outline_width", "caption_shadow_depth", "caption_vertical_margin_percent", "caption_bold", "caption_animation", "caption_animation_duration", "caption_highlight_color"):
        if key in render_settings and render_settings[key] is not None:
            merged[key] = render_settings[key]
    return merged


def _captions_enabled_for(base_config: dict, candidate_state: dict) -> bool:
    render_settings = candidate_state.get("render_settings", {})
    if isinstance(render_settings, dict) and render_settings.get("captions_enabled") is not None:
        return bool(render_settings.get("captions_enabled"))
    return bool(base_config.get("captions_enabled", True))


def _caption_segments_for(candidate_state: dict, transcript_segments: list[dict]) -> list[dict]:
    segments = candidate_state.get("caption_segments", [])
    if isinstance(segments, list) and segments:
        cleaned: list[dict] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            if {"start", "end", "text"}.issubset(segment.keys()):
                cleaned.append({"start": segment["start"], "end": segment["end"], "text": segment["text"]})
        if cleaned:
            return cleaned
    return transcript_segments


def submit_renders(
    video_id: str,
    candidate_ids: list[int],
    overrides: dict[int, object] | None = None,
    candidate_states: dict[int, object] | None = None,
    retry_of: str | None = None,
    batch_id: str | None = None,
    preflight_only: bool = False,
    editing: EditingSettings | dict | None = None,
    owner_id: str | None = None,
) -> list[str]:
    selected = validate_candidate_ids(video_id, candidate_ids)
    override_map = overrides or {}
    state_map = candidate_states or {}
    unknown_overrides = [candidate_id for candidate_id in override_map if candidate_id not in selected]
    if unknown_overrides:
        raise ValueError(f"Trim override provided for unknown candidate(s): {', '.join(str(candidate_id) for candidate_id in unknown_overrides)}")
    unknown_states = [candidate_id for candidate_id in state_map if candidate_id not in selected]
    if unknown_states:
        raise ValueError(f"Editor state provided for unknown candidate(s): {', '.join(str(candidate_id) for candidate_id in unknown_states)}")

    metadata = load_project_metadata(video_id) or {}
    source_path = Path(metadata.get("source_path") or "")
    if not source_path.exists():
        source_key = metadata.get("source_storage_key")
        if not isinstance(source_key, str) or not source_key:
            raise FileNotFoundError("Cached source video is missing.")
        source_path = PROCESSING_TEMP_DIR / "youtube" / video_id / Path(source_key).name
        storage.download_file(source_key, source_path)
        if not source_path.is_file() or source_path.stat().st_size == 0:
            raise FileNotFoundError("Cached source video could not be restored from durable storage.")
        metadata["source_path"] = str(source_path)
        save_project_metadata(video_id, metadata)

    try:
        source_info = get_media_info(source_path)
    except Exception:
        source_info = {"duration": None}

    base_config = load_config()
    source_duration = float(source_info.get("duration")) if source_info.get("duration") is not None else None
    editing_settings = EditingSettings.model_validate(editing) if editing is not None else None
    if editing_settings is not None and editing_settings.transition != "hard_cut":
        raise ValueError("Compilation transitions are only supported for Auto-Compilation.")
    if editing_settings is not None and editing_settings.music is not None:
        if owner_id is None or project_owner_id(video_id) != owner_id:
            raise FileNotFoundError("Project not found.")
        if find_music_asset(video_id, editing_settings.music.asset_id, owner_id=owner_id) is None:
            raise ValueError("The selected project music asset was not found.")
    base_config = apply_caption_preset(base_config, editing_settings)

    request_snapshots: dict[int, dict] = {}
    for candidate_id, candidate in selected.items():
        candidate_state = _candidate_state_for(video_id, candidate_id, state_map.get(candidate_id))
        override = override_map.get(candidate_id)
        trim_source = override or (candidate_state.get("trim") if isinstance(candidate_state, dict) else None)
        start, end = _selected_bounds(candidate, trim_source)
        _validate_bounds(
            start,
            end,
            min_seconds=float(base_config.get("clip_min_seconds", 10)),
            max_seconds=float(base_config.get("clip_max_seconds", 60)),
            source_duration=source_duration,
        )
        effective_config = _render_config_for(base_config, candidate_state)
        if editing_settings is not None:
            validate_editing_timing(editing_settings, end - start)
        request_signature = {
            "video_id": video_id,
            "candidate_id": candidate_id,
            "start": start,
            "end": end,
            "render_settings": {
                "output_width": effective_config.get("output_width"),
                "output_height": effective_config.get("output_height"),
                "fps": effective_config.get("fps"),
                "captions_enabled": _captions_enabled_for(effective_config, candidate_state),
                "normalize_audio": effective_config.get("normalize_audio"),
                **{key: effective_config.get(key) for key in ("caption_font_name", "caption_font_size", "caption_primary_color", "caption_outline_color", "caption_shadow_color", "caption_outline_width", "caption_shadow_depth", "caption_vertical_margin_percent", "caption_bold", "caption_preset_id", "caption_animation", "caption_animation_duration", "caption_highlight_color")},
            },
            "caption_segments": _caption_segments_for(candidate_state, []),
        }
        if editing_settings is not None:
            request_signature["editing"] = editing_settings.model_dump()
        request_snapshots[candidate_id] = request_signature

    for existing in job_registry.list():
        if existing.kind != "render" or existing.status not in {"queued", "running"}:
            continue
        existing_signature = None
        if isinstance(existing.result, dict):
            existing_signature = existing.result.get("request_signature")
        if existing_signature in request_snapshots.values():
            raise ValueError("An identical render job is already queued or running.")

    if preflight_only:
        return []

    job_ids: list[str] = []
    for candidate_id, candidate in selected.items():
        candidate_state = _candidate_state_for(video_id, candidate_id, state_map.get(candidate_id))
        selected_override = override_map.get(candidate_id)
        effective_config = _render_config_for(base_config, candidate_state)
        request_signature = request_snapshots[candidate_id]
        record = job_registry.create(
            "render",
            video_id=video_id,
            candidate_id=candidate_id,
            stage="queued",
            message="Waiting",
            result={"request_signature": request_signature, **({"batch_id": batch_id} if batch_id else {})},
            retry_of=retry_of,
            percent=0.0,
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            artifact_kind="clip",
        )

        def _runner(
            job_id: str,
            selected_candidate: dict = candidate,
            trim_override: object | None = selected_override,
            selected_state: dict = candidate_state,
            selected_config: dict = effective_config,
            signature: dict = request_signature,
            selected_editing: EditingSettings | None = editing_settings,
            selected_owner: str | None = owner_id,
        ) -> None:
            ass_path: Path | None = None
            effect_temp_dir: Path | None = None
            try:
                metadata_local = load_project_metadata(video_id) or {}
                source_path_local = Path(metadata_local.get("source_path") or "")
                if not source_path_local.exists():
                    source_key = metadata_local.get("source_storage_key")
                    if not isinstance(source_key, str):
                        raise FileNotFoundError("Cached source video is missing.")
                    source_path_local = PROCESSING_TEMP_DIR / "youtube" / video_id / Path(source_key).name
                    storage.download_file(source_key, source_path_local)
                transcript_file = PROCESSING_TEMP_DIR / "youtube" / video_id / "transcript.json"
                if not transcript_file.exists():
                    raise FileNotFoundError("Cached transcript is missing.")
                transcript = load_transcript(transcript_file)
                start, end = _selected_bounds(selected_candidate, trim_override or (selected_state.get("trim") if isinstance(selected_state, dict) else None))
                transcript_segments = _caption_segments_for(selected_state, transcript["segments"])
                cues = build_caption_cues(
                    transcript_segments,
                    start,
                    end,
                    max_words_per_chunk=base_config.get("caption_max_words_per_segment", 5),
                    max_chars_per_line=base_config.get("caption_max_chars_per_line", 18),
                    max_lines=base_config.get("caption_max_lines", 2),
                )
                if cues and _captions_enabled_for(selected_config, selected_state):
                    ass_path = PROCESSING_TEMP_DIR / f"{video_id}_{candidate_id}.ass"
                    write_ass_subtitles(cues, selected_config, ass_path)
                artifact_id = job_registry.get(job_id).artifact_id if job_registry.get(job_id) else None
                if not artifact_id:
                    raise RuntimeError("Render artifact identity is missing.")
                output_path = OUTPUT_SHORTS_DIR / f"short_{artifact_id}.mp4"
                expected_duration = max(end - start, 0.001)

                def on_progress(progress: dict[str, str]) -> None:
                    raw_time = progress.get("out_time_us") or progress.get("out_time_ms")
                    if raw_time in (None, "N/A"):
                        return
                    try:
                        rendered_seconds = float(raw_time) / 1_000_000
                    except (TypeError, ValueError):
                        return
                    percent = min(99.0, max(0.0, rendered_seconds / expected_duration * 100.0))
                    job_registry.update(job_id, percent=percent)

                job_registry.update(job_id, status="running", stage="rendering", message="Rendering captions...", percent=0.0)
                render_short(source_path_local, start, end, selected_config, ass_path, output_path, progress_callback=on_progress)
                if selected_editing is not None:
                    effect_temp_dir = PROCESSING_TEMP_DIR / "smart-editing" / job_id
                    music_path = None
                    if selected_editing.music is not None:
                        if selected_owner is None:
                            raise FileNotFoundError("Project music owner is unavailable.")
                        music_path = download_project_music(
                            video_id,
                            selected_editing.music.asset_id,
                            owner_id=selected_owner,
                            destination_dir=effect_temp_dir,
                        )
                    apply_smart_effects(
                        output_path,
                        settings=selected_editing,
                        duration_seconds=end - start,
                        config=selected_config,
                        has_original_audio=bool(source_info.get("has_audio")),
                        temp_dir=effect_temp_dir or PROCESSING_TEMP_DIR,
                        music_path=music_path,
                    )
                require_audio = (
                    selected_editing is None
                    or bool(source_info.get("has_audio"))
                    or (selected_editing.music is not None)
                )
                problems = verify_output(
                    output_path,
                    selected_config,
                    expected_duration=end - start,
                    require_audio=require_audio,
                )
                if problems:
                    raise RuntimeError("; ".join(problems))
                output_key = f"projects/{video_id}/renders/{artifact_id}/{output_path.name}"
                if storage.exists(output_key):
                    raise RuntimeError("Render output already exists; refusing to overwrite it.")
                storage.upload_file(output_path, output_key, "video/mp4")
                register_render_output(
                    video_id,
                    output_path.name,
                    artifact_id=artifact_id,
                    job_id=job_id,
                    storage_key=output_key,
                )
                patched = patch_project_metadata(
                    video_id,
                    status=metadata_local.get("status", "completed"),
                    analysis_stage=metadata_local.get("analysis_stage", "complete"),
                    message=metadata_local.get("message", "Complete"),
                )
                save_project_metadata(video_id, patched)
                job_registry.update(
                    job_id,
                    status="completed",
                    stage="complete",
                    message="Complete",
                    output_path=str(output_path),
                    output_url=f"/api/media/artifacts/{artifact_id}",
                    percent=100.0,
                    result={"request_signature": signature, "start": start, "end": end, "render_settings": signature["render_settings"], "output_storage_key": output_key, "artifact_id": artifact_id, **({"batch_id": batch_id} if batch_id else {})},
                )
                if batch_id:
                    from backend.services.batch_service import refresh_batch

                    refresh_batch(batch_id)
            except Exception as exc:
                if ass_path is not None:
                    ass_path.unlink(missing_ok=True)
                job_registry.update(job_id, status="failed", stage="failed", message="Rendering failed.", error=str(exc), result={"request_signature": signature, **({"batch_id": batch_id} if batch_id else {})})
                if batch_id:
                    from backend.services.batch_service import refresh_batch

                    refresh_batch(batch_id)
            else:
                if ass_path is not None:
                    ass_path.unlink(missing_ok=True)
            finally:
                if effect_temp_dir is not None:
                    try:
                        shutil.rmtree(effect_temp_dir)
                    except FileNotFoundError:
                        pass

        thread = threading.Thread(target=_runner, args=(record.id,), daemon=True)
        thread.start()
        job_ids.append(record.id)
    return job_ids


def list_render_jobs(owner_id: str) -> list[dict]:
    from backend.services.project_service import project_owner_id

    return [
        record.to_dict()
        for record in job_registry.list()
        if record.kind == "render"
        and record.video_id
        and project_owner_id(record.video_id) == owner_id
    ]


def get_render_job(job_id: str, *, owner_id: str) -> dict | None:
    record = job_registry.get(job_id)
    if record is None or record.kind != "render":
        return None
    from backend.services.project_service import project_owner_id

    if not record.video_id or project_owner_id(record.video_id) != owner_id:
        return None
    return record.to_dict()


def delete_render_job(job_id: str) -> bool:
    record = job_registry.get(job_id)
    if record is None or record.kind != "render":
        return False
    if record.status not in {"completed", "failed", "interrupted"}:
        raise ValueError("Only completed, failed, or interrupted jobs can be removed from the queue.")
    return job_registry.remove(job_id)


def retry_render_job(job_id: str) -> list[str]:
    record = job_registry.get(job_id)
    if record is None or record.kind != "render":
        raise FileNotFoundError("Render job not found.")
    if record.status not in {"failed", "completed"}:
        raise ValueError("Only completed or failed jobs can be retried.")
    if not isinstance(record.result, dict):
        raise ValueError("Render job does not contain a retryable request snapshot.")
    request = record.result.get("request_signature")
    if not isinstance(request, dict):
        raise ValueError("Render job does not contain a retryable request snapshot.")
    candidate_id = int(request.get("candidate_id"))
    start = float(request.get("start"))
    end = float(request.get("end"))
    candidate_state = {
        "trim": {"start": start, "end": end},
        "caption_segments": request.get("caption_segments", []),
        "render_settings": request.get("render_settings", {}),
    }
    return submit_renders(
        request.get("video_id", record.video_id or ""),
        [candidate_id],
        candidate_states={candidate_id: candidate_state},
        retry_of=record.id,
        editing=request.get("editing"),
        owner_id=project_owner_id(request.get("video_id", record.video_id or "")),
    )
