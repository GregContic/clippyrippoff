from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import CandidateListResponse, CandidateResponse
from backend.services.project_service import load_candidates, project_summary

router = APIRouter(prefix="/api/videos", tags=["candidates"])


@router.get("/{video_id}/candidates", response_model=CandidateListResponse)
def get_candidates(video_id: str) -> CandidateListResponse:
    payload = load_candidates(video_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No candidates are available for this video yet.")
    summary = project_summary(video_id) or {}
    preview_url = summary.get("source_video_url")
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    return CandidateListResponse(
        video_id=video_id,
        candidates=[
            CandidateResponse(**{**candidate, "preview_url": preview_url})
            for candidate in candidates
        ],
        candidate_count=len(candidates),
    )
