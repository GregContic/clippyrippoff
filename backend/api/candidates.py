from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import CandidateListResponse, CandidateResponse, CandidateEditorState, ProjectEditorState, TrimBounds
from backend.services.project_service import get_candidate_editor_state, load_candidates, project_summary, set_candidate_editor_state, source_duration
from scripts.utils import ValidationError as ClipValidationError, load_config, validate_clip_range

router = APIRouter(prefix="/api/videos", tags=["candidates"])


def _candidate_response(video_id: str, candidate: dict, preview_url: str | None) -> CandidateResponse:
    candidate_state = get_candidate_editor_state(video_id, int(candidate["id"]))
    manual_trim = candidate_state.get("trim") if isinstance(candidate_state, dict) else None
    trim_start = manual_trim.get("start") if manual_trim else None
    trim_end = manual_trim.get("end") if manual_trim else None
    return CandidateResponse(
        **{**candidate, "preview_url": preview_url, "trim_start": trim_start, "trim_end": trim_end, "trim_saved": manual_trim is not None},
    )


@router.get("/{video_id}/candidates", response_model=CandidateListResponse)
def get_candidates(video_id: str) -> CandidateListResponse:
    payload = load_candidates(video_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No candidates are available for this video yet.")
    summary = project_summary(video_id) or {}
    preview_url = summary.get("source_video_url")
    source_duration_value = source_duration(video_id)
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    return CandidateListResponse(
        video_id=video_id,
        source_duration=source_duration_value,
        candidates=[_candidate_response(video_id, candidate, preview_url) for candidate in candidates],
        candidate_count=len(candidates),
    )


@router.put("/{video_id}/candidates/{candidate_id}/trim", response_model=CandidateResponse)
def save_candidate_trim(video_id: str, candidate_id: int, request: TrimBounds) -> CandidateResponse:
    payload = load_candidates(video_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No candidates are available for this video yet.")
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    matching = next((candidate for candidate in candidates if int(candidate.get("id", -1)) == candidate_id), None)
    if matching is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    source_duration_value = source_duration(video_id)
    config = load_config()
    try:
        validate_clip_range(
            request.start,
            request.end,
            min_seconds=float(config.get("clip_min_seconds", 10)),
            max_seconds=float(config.get("clip_max_seconds", 60)),
            video_duration=source_duration_value,
        )
    except ClipValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    candidate_state = get_candidate_editor_state(video_id, candidate_id)
    if not isinstance(candidate_state, dict):
        candidate_state = {}
    candidate_state["trim"] = {"start": request.start, "end": request.end}
    candidate_state.setdefault("caption_segments", [])
    candidate_state.setdefault("render_settings", {})
    candidate_state.setdefault("selected", False)
    set_candidate_editor_state(video_id, candidate_id, candidate_state)
    summary = project_summary(video_id) or {}
    preview_url = summary.get("source_video_url")
    return _candidate_response(video_id, matching, preview_url)
