from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import LibraryItem, LibraryResponse
from backend.services.project_service import delete_library_item, list_library_items

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("", response_model=LibraryResponse)
def get_library() -> LibraryResponse:
    return LibraryResponse(items=[LibraryItem(**item) for item in list_library_items()])


@router.delete("/{filename}")
def delete_library_file(filename: str) -> dict[str, str]:
    try:
        delete_library_item(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Short not found.")
    return {"status": "deleted"}
