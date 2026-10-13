from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.schemas import MusicAssetResponse
from backend.services.music_asset_service import list_project_music, upload_music_asset
from backend.services.storage import StorageError

router = APIRouter(prefix="/api/projects", tags=["music"])


@router.get("/{video_id}/music", response_model=list[MusicAssetResponse])
def get_project_music(video_id: str, request: Request) -> list[MusicAssetResponse]:
    try:
        items = list_project_music(video_id, owner_id=request.state.user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Project music storage is temporarily unavailable.") from exc
    return [MusicAssetResponse(**item) for item in items]


@router.post("/{video_id}/music", response_model=MusicAssetResponse, status_code=201)
def add_project_music(video_id: str, request: Request, file: UploadFile = File(...)) -> MusicAssetResponse:
    try:
        asset = upload_music_asset(
            video_id,
            owner_id=request.state.user.id,
            filename=file.filename or "",
            content_type=file.content_type,
            stream=file.file,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Project music storage is temporarily unavailable.") from exc
    return MusicAssetResponse(**asset)
