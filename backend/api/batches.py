from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import BatchRequest, BatchResponse
from backend.services.batch_service import create_batch, get_batch
from backend.services.storage import StorageError

router = APIRouter(prefix="/api", tags=["batches"])


@router.post("/projects/{video_id}/batches", response_model=BatchResponse)
def start_batch(video_id: str, request_data: BatchRequest, request: Request) -> BatchResponse:
    try:
        batch = create_batch(
            video_id,
            owner_id=request.state.user.id,
            target_duration_seconds=request_data.target_duration_seconds,
            minimum_spacing_seconds=request_data.minimum_spacing_seconds,
            max_clips=request_data.max_clips,
            candidate_ids=request_data.candidate_ids,
            render_settings=request_data.render_settings.model_dump(exclude_none=True) if request_data.render_settings else None,
            editing=request_data.editing.model_dump() if request_data.editing else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Batch state storage is temporarily unavailable.") from exc
    return BatchResponse(**batch)


@router.get("/batches/{batch_id}", response_model=BatchResponse)
def read_batch(batch_id: str, request: Request) -> BatchResponse:
    try:
        batch = get_batch(batch_id, owner_id=request.state.user.id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Batch state storage is temporarily unavailable.") from exc
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return BatchResponse(**batch)
