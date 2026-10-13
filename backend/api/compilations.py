from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import CompilationRequest, CompilationResponse
from backend.services.compilation_service import create_compilation, get_compilation
from backend.services.storage import StorageError

router = APIRouter(prefix="/api", tags=["compilations"])


@router.post("/projects/{video_id}/compilations", response_model=CompilationResponse)
def start_compilation(
    video_id: str,
    request_data: CompilationRequest,
    request: Request,
) -> CompilationResponse:
    try:
        compilation = create_compilation(
            video_id,
            owner_id=request.state.user.id,
            segments=[segment.model_dump() for segment in request_data.segments],
            max_total_duration_seconds=request_data.max_total_duration_seconds,
            render_settings=(
                request_data.render_settings.model_dump(exclude_none=True)
                if request_data.render_settings
                else None
            ),
            editing=request_data.editing,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Compilation storage is temporarily unavailable.") from exc
    return CompilationResponse(**compilation)


@router.get("/compilations/{compilation_id}", response_model=CompilationResponse)
def read_compilation(compilation_id: str, request: Request) -> CompilationResponse:
    try:
        compilation = get_compilation(compilation_id, owner_id=request.state.user.id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Compilation storage is temporarily unavailable.") from exc
    if compilation is None:
        raise HTTPException(status_code=404, detail="Compilation not found.")
    return CompilationResponse(**compilation)
