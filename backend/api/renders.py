from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.schemas import JobResponse, RenderRequest, RenderResponse, ReviewRequest
from backend.services.job_registry import job_registry
from scripts.utils import OUTPUT_SHORTS_DIR
from backend.services.render_service import TrimValidationError, delete_render_job, get_render_job, list_render_jobs, retry_render_job, submit_renders

router = APIRouter(prefix="/api", tags=["renders"])


@router.post("/videos/{video_id}/render", response_model=RenderResponse)
def render_candidates(video_id: str, request: RenderRequest) -> RenderResponse:
    try:
        overrides = {int(candidate_id): trim for candidate_id, trim in request.overrides.items()}
        candidate_states = {int(candidate_id): state for candidate_id, state in request.candidate_states.items()}
        job_ids = submit_renders(video_id, request.candidate_ids, overrides=overrides, candidate_states=candidate_states)
    except TrimValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.patch("/renders/{render_id}/review", response_model=JobResponse)
def review_render(render_id: str, request: ReviewRequest) -> JobResponse:
    record = get_render_job(render_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Render job not found.")
    if record.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Only completed renders can be reviewed.")
    output_path = record.get("output_path")
    safe_output = (OUTPUT_SHORTS_DIR / Path(output_path).name).resolve() if output_path else None
    if not output_path or safe_output is None or safe_output.parent != OUTPUT_SHORTS_DIR.resolve() or not safe_output.is_file():
        raise HTTPException(status_code=400, detail="The rendered output file is missing; approval is unavailable.")
    updated = job_registry.update(render_id, review_status=request.status, review_notes=request.notes.strip())
    return JobResponse(**updated.to_dict())


@router.delete("/renders/{render_id}")
def remove_render(render_id: str) -> dict[str, str]:
    try:
        removed = delete_render_job(render_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Render job not found.")
    return {"status": "deleted"}


@router.post("/renders/{render_id}/retry", response_model=RenderResponse)
def retry_render(render_id: str) -> RenderResponse:
    try:
        job_ids = retry_render_job(render_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    record = get_render_job(render_id)
    return RenderResponse(video_id=record.get("video_id") if record else "", render_job_ids=job_ids)
