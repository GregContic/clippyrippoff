from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import JobResponse, RenderRequest, RenderResponse
from backend.services.render_service import delete_render_job, get_render_job, list_render_jobs, submit_renders

router = APIRouter(prefix="/api", tags=["renders"])


@router.post("/videos/{video_id}/render", response_model=RenderResponse)
def render_candidates(video_id: str, request: RenderRequest) -> RenderResponse:
    try:
        job_ids = submit_renders(video_id, request.candidate_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RenderResponse(video_id=video_id, render_job_ids=job_ids)


@router.get("/renders", response_model=list[JobResponse])
def get_renders() -> list[JobResponse]:
    return [JobResponse(**item) for item in list_render_jobs()]


@router.get("/renders/{render_id}", response_model=JobResponse)
def get_render(render_id: str) -> JobResponse:
    record = get_render_job(render_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Render job not found.")
    return JobResponse(**record)


@router.delete("/renders/{render_id}")
def remove_render(render_id: str) -> dict[str, str]:
    try:
        removed = delete_render_job(render_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Render job not found.")
    return {"status": "deleted"}
