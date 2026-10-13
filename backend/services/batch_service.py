from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.services.job_registry import job_registry
from backend.services.project_service import (
    find_batch as find_persisted_batch,
    load_candidates,
    project_owner_id,
    save_batch_record,
    source_duration,
)
from backend.services.render_service import submit_renders
from backend.services.storage import StorageError
from scripts.utils import load_config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_bounds(candidate: dict[str, Any], target: float, source_duration: float | None) -> tuple[float, float] | None:
    try:
        original_start = float(candidate["start"])
        original_end = float(candidate["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(original_start) or not math.isfinite(original_end):
        return None
    start = max(0.0, original_start)
    end = min(original_end, source_duration) if source_duration is not None else original_end
    if end <= start:
        return None
    duration = end - start
    if duration > target:
        trigger = candidate.get("trigger_time")
        center = float(trigger) if isinstance(trigger, (int, float)) and math.isfinite(float(trigger)) else (start + end) / 2.0
        window_start = min(max(center - target / 2.0, start), end - target)
        start, end = window_start, window_start + target
    return (start, end) if end - start >= 0 else None


def select_batch_candidates(
    video_id: str,
    *,
    target_duration_seconds: float,
    minimum_spacing_seconds: float,
    max_clips: int | None,
    candidate_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """Select highest-scoring valid moments; ties use the lower candidate ID.

    A candidate is skipped when its bounded render window overlaps a selected
    window or its trigger/midpoint is closer than the requested spacing.
    """
    payload = load_candidates(video_id)
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise ValueError("No analyzed candidates are available for batch clips.")
    config = load_config()
    minimum = float(config.get("clip_min_seconds", 10))
    maximum = float(config.get("clip_max_seconds", 60))
    if target_duration_seconds < minimum or target_duration_seconds > maximum:
        raise ValueError(f"Target duration must be between {minimum:g} and {maximum:g} seconds.")
    requested = set(candidate_ids or [])
    source_duration_value = source_duration(video_id)
    candidates = []
    for raw in payload["candidates"]:
        if not isinstance(raw, dict):
            continue
        try:
            candidate_id = int(raw["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if requested and candidate_id not in requested:
            continue
        bounds = _candidate_bounds(raw, target_duration_seconds, source_duration_value)
        if bounds is not None and bounds[1] - bounds[0] >= minimum:
            try:
                score = float(raw.get("candidate_score", 0))
            except (TypeError, ValueError):
                score = 0.0
            if not math.isfinite(score):
                score = 0.0
            candidates.append((score, candidate_id, raw, bounds))
    if requested:
        found = {candidate_id for _, candidate_id, _, _ in candidates}
        missing = sorted(requested - found)
        if missing:
            raise ValueError(f"Candidate(s) cannot produce a valid batch clip: {', '.join(map(str, missing))}")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    limit = max_clips if max_clips is not None else min(len(candidates), int(config.get("max_candidates", len(candidates) or 1)))
    selected: list[dict[str, Any]] = []
    for _, candidate_id, raw, bounds in candidates:
        if len(selected) >= limit:
            break
        start, end = bounds
        trigger_value = raw.get("trigger_time")
        try:
            moment = float(trigger_value) if trigger_value is not None else (start + end) / 2.0
        except (TypeError, ValueError):
            moment = (start + end) / 2.0
        if any(
            not (end <= item["start"] or start >= item["end"])
            or abs(moment - item["moment"]) < minimum_spacing_seconds
            for item in selected
        ):
            continue
        selected.append({"candidate_id": candidate_id, "start": start, "end": end, "moment": moment})
    if not selected:
        raise ValueError("No candidates can produce valid clips with the requested spacing and duration.")
    return selected


def _child_payload(batch: dict[str, Any], child_id: str) -> dict[str, Any]:
    child = job_registry.get(child_id)
    if child is None:
        return {"job_id": child_id, "status": "missing", "percent": 0.0}
    result = child.result if isinstance(child.result, dict) else {}
    signature = result.get("request_signature") if isinstance(result.get("request_signature"), dict) else {}
    return {
        "job_id": child.id,
        "status": child.status,
        "percent": float(child.percent or 0.0),
        "candidate_id": child.candidate_id,
        "start": signature.get("start"),
        "end": signature.get("end"),
        "artifact_id": child.artifact_id,
        "output_url": child.output_url,
        "error": child.error,
    }


def refresh_batch(batch_id: str) -> dict[str, Any] | None:
    batch = find_persisted_batch(batch_id)
    if batch is None:
        return None
    parent_id = batch.get("parent_job_id")
    child_ids = batch.get("child_job_ids")
    if not isinstance(parent_id, str) or not isinstance(child_ids, list):
        return batch
    parent = job_registry.update_parent_from_children(parent_id, [str(child_id) for child_id in child_ids])
    if parent is not None:
        batch["status"] = parent.status
        batch["percent"] = parent.percent
        batch["updated_at"] = parent.updated_at
        if parent.status in {"completed", "partially_completed", "failed"}:
            batch["completed_at"] = (parent.result or {}).get("completed_at", parent.updated_at)
        save_batch_record(str(batch["project_id"]), batch)
    return batch


def create_batch(
    video_id: str,
    *,
    owner_id: str,
    target_duration_seconds: float,
    minimum_spacing_seconds: float,
    max_clips: int | None,
    candidate_ids: list[int] | None,
    render_settings: dict[str, Any] | None,
    editing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if project_owner_id(video_id) != owner_id:
        raise FileNotFoundError("Project not found.")
    selection = select_batch_candidates(
        video_id,
        target_duration_seconds=target_duration_seconds,
        minimum_spacing_seconds=minimum_spacing_seconds,
        max_clips=max_clips,
        candidate_ids=candidate_ids,
    )
    batch_id = f"batch-{uuid.uuid4().hex}"
    states = {}
    if render_settings is not None:
        states = {
            item["candidate_id"]: {
                "render_settings": render_settings,
                "caption_segments": [],
                "selected": True,
            }
            for item in selection
        }
    overrides = {item["candidate_id"]: {"start": item["start"], "end": item["end"]} for item in selection}
    submit_renders(
        video_id,
        [item["candidate_id"] for item in selection],
        overrides=overrides,
        candidate_states=states,
        preflight_only=True,
        editing=editing,
        owner_id=owner_id,
    )
    parent = job_registry.create(
        "batch",
        video_id=video_id,
        stage="queued",
        message="Batch queued.",
        result={"batch_id": batch_id, "child_job_ids": []},
        percent=0.0,
    )
    record = {
        "batch_id": batch_id,
        "project_id": video_id,
        "owner_id": owner_id,
        "parent_job_id": parent.id,
        "child_job_ids": [],
        "selection": selection,
        "target_duration_seconds": target_duration_seconds,
        "minimum_spacing_seconds": minimum_spacing_seconds,
        "created_at": parent.created_at,
        "status": parent.status,
        "percent": parent.percent,
    }
    save_batch_record(video_id, record)
    try:
        child_ids = submit_renders(
            video_id,
            [item["candidate_id"] for item in selection],
            overrides=overrides,
            candidate_states=states,
            batch_id=batch_id,
            editing=editing,
            owner_id=owner_id,
        )
    except (FileNotFoundError, ValueError, StorageError) as exc:
        failed = job_registry.update(parent.id, status="failed", stage="failed", message="Batch submission failed.", error=str(exc), percent=0.0)
        save_batch_record(video_id, {**record, "status": failed.status, "updated_at": failed.updated_at, "completed_at": failed.updated_at})
        raise
    parent = job_registry.update(parent.id, result={"batch_id": batch_id, "child_job_ids": child_ids})
    record["child_job_ids"] = child_ids
    record["status"] = parent.status
    record["updated_at"] = parent.updated_at
    save_batch_record(video_id, record)
    return get_batch(batch_id, owner_id=owner_id) or record


def get_batch(batch_id: str, *, owner_id: str) -> dict[str, Any] | None:
    batch = find_persisted_batch(batch_id, owner_id=owner_id)
    if batch is None:
        return None
    batch = refresh_batch(batch_id)
    if batch is None or batch.get("owner_id") != owner_id:
        return None
    children = batch.get("child_job_ids", [])
    batch["children"] = [_child_payload(batch, str(child_id)) for child_id in children]
    return batch
