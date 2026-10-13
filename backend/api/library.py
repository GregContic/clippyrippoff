from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import LibraryItem, LibraryResponse
from backend.services.project_service import delete_artifact, delete_library_item, list_library_items
from backend.services.storage import StorageError

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("", response_model=LibraryResponse)
def get_library(request: Request) -> LibraryResponse:
    try:
        items = list_library_items(request.state.user.id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Library storage is temporarily unavailable.") from exc
    return LibraryResponse(items=[LibraryItem(**item) for item in items])


@router.delete("/artifacts/{artifact_id}")
def delete_library_artifact(artifact_id: str, request: Request) -> dict[str, str]:
    try:
        delete_artifact(artifact_id, request.state.user.id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Artifact storage is temporarily unavailable.") from exc
    return {"status": "deleted"}


@router.delete("/{filename}")
def delete_library_file(filename: str, request: Request) -> dict[str, str]:
    try:
        delete_library_item(filename, request.state.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Short not found.")
    return {"status": "deleted"}
