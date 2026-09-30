from fastapi import APIRouter, HTTPException

from backend.schemas import CaptionPreset, CaptionPresetRequest
from backend.services.caption_preset_service import delete_preset, list_presets, save_preset

router = APIRouter(prefix="/api/caption-presets", tags=["caption-presets"])


@router.get("", response_model=list[CaptionPreset])
def get_presets() -> list[CaptionPreset]:
    return list_presets()


@router.post("", response_model=CaptionPreset)
def create_preset(request: CaptionPresetRequest) -> CaptionPreset:
    return save_preset(request)


@router.put("/{preset_id}", response_model=CaptionPreset)
def update_preset(preset_id: str, request: CaptionPresetRequest) -> CaptionPreset:
    try:
        return save_preset(request, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{preset_id}")
def remove_preset(preset_id: str) -> dict[str, str]:
    try:
        delete_preset(preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}