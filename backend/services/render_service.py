from __future__ import annotations

import threading
from pathlib import Path

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.services.job_registry import job_registry
from backend.services.project_service import (
    load_candidates,
    load_project_metadata,
    patch_project_metadata,
    register_render_output,
    save_project_metadata,
)
from scripts.make_short import build_caption_cues, render_short, verify_output, write_ass_subtitles
from scripts.utils import OUTPUT_SHORTS_DIR, PROCESSING_TEMP_DIR, generate_output_filename, load_config, load_transcript


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


def submit_renders(video_id: str, candidate_ids: list[int]) -> list[str]:
    selected = validate_candidate_ids(video_id, candidate_ids)
    job_ids: list[str] = []
    for candidate_id, candidate in selected.items():
        record = job_registry.create(
            "render",
            video_id=video_id,
            candidate_id=candidate_id,
            stage="queued",
            message="Waiting",
        )

        def _runner(job_id: str, selected_candidate: dict = candidate) -> None:
            try:
                metadata = load_project_metadata(video_id) or {}
                source_path = Path(metadata.get("source_path") or "")
                if not source_path.exists():
                    raise FileNotFoundError("Cached source video is missing.")
                transcript_file = PROCESSING_TEMP_DIR / "youtube" / video_id / "transcript.json"
                if not transcript_file.exists():
                    raise FileNotFoundError("Cached transcript is missing.")
                transcript = load_transcript(transcript_file)
                config = load_config()
                start = float(selected_candidate["start"])
                end = float(selected_candidate["end"])
                cues = build_caption_cues(
                    transcript["segments"],
                    start,
                    end,
                    max_words_per_chunk=config.get("caption_max_words_per_segment", 5),
                    max_chars_per_line=config.get("caption_max_chars_per_line", 18),
                    max_lines=config.get("caption_max_lines", 2),
                )
                ass_path = None
                if cues:
                    ass_path = PROCESSING_TEMP_DIR / f"{video_id}_{candidate_id}.ass"
                    write_ass_subtitles(cues, config, ass_path)
                output_path = generate_output_filename(OUTPUT_SHORTS_DIR)
                job_registry.update(job_id, status="running", stage="rendering", message="Rendering captions...")
                render_short(source_path, start, end, config, ass_path, output_path)
                problems = verify_output(output_path, config, expected_duration=end - start)
                if problems:
                    raise RuntimeError("; ".join(problems))
                register_render_output(video_id, output_path.name)
                patched = patch_project_metadata(
                    video_id,
                    status=metadata.get("status", "completed"),
                    analysis_stage=metadata.get("analysis_stage", "complete"),
                    message=metadata.get("message", "Complete"),
                )
                save_project_metadata(video_id, patched)
                job_registry.update(
                    job_id,
                    status="completed",
                    stage="complete",
                    message="Complete",
                    output_path=str(output_path),
                    output_url=f"/media/shorts/{output_path.name}",
                )
            except Exception as exc:
                job_registry.update(job_id, status="failed", stage="failed", message="Rendering failed.", error=str(exc))

        thread = threading.Thread(target=_runner, args=(record.id,), daemon=True)
        thread.start()
        job_ids.append(record.id)
    return job_ids


def list_render_jobs() -> list[dict]:
    return [record.to_dict() for record in job_registry.list() if record.kind == "render"]


def get_render_job(job_id: str) -> dict | None:
    record = job_registry.get(job_id)
    if record is None or record.kind != "render":
        return None
    return record.to_dict()


def delete_render_job(job_id: str) -> bool:
    record = job_registry.get(job_id)
    if record is None or record.kind != "render":
        return False
    if record.status not in {"completed", "failed"}:
        raise ValueError("Only completed or failed jobs can be removed from the queue.")
    return job_registry.remove(job_id)
