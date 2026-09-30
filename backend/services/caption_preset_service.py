from __future__ import annotations

import uuid
from typing import Any

from backend.schemas import CaptionPreset, CaptionPresetRequest, RenderSettings
from backend.services.project_service import read_json, write_json
from scripts.utils import PROCESSING_TEMP_DIR

PRESETS_PATH = PROCESSING_TEMP_DIR / "caption_presets.json"


def _settings(**values: Any) -> RenderSettings:
    return RenderSettings(**values)


def built_in_presets() -> list[CaptionPreset]:
    common = {"caption_primary_color": "&H00FFFFFF", "caption_outline_color": "&H00000000", "caption_shadow_color": "&H80000000"}
    animated = {"caption_animation_duration": 0.16, "caption_highlight_color": "&H0000FFFF"}
    return [
        CaptionPreset(id="clean", name="Clean", built_in=True, settings=_settings(caption_font_name="Arial", caption_font_size=64, caption_outline_width=3, caption_shadow_depth=2, caption_vertical_margin_percent=0.28, caption_bold=True, **common)),
        CaptionPreset(id="bold", name="Bold", built_in=True, settings=_settings(caption_font_name="Arial Black", caption_font_size=82, caption_outline_width=5, caption_shadow_depth=3, caption_vertical_margin_percent=0.3, caption_bold=True, **common)),
        CaptionPreset(id="gaming", name="Gaming", built_in=True, settings=_settings(caption_font_name="Verdana", caption_font_size=76, caption_primary_color="&H0000FFFF", caption_outline_width=4, caption_shadow_depth=4, caption_vertical_margin_percent=0.32, caption_bold=True, caption_outline_color="&H00000000", caption_shadow_color="&H80000000")),
        CaptionPreset(id="minimal", name="Minimal", built_in=True, settings=_settings(caption_font_name="Arial", caption_font_size=52, caption_outline_width=2, caption_shadow_depth=1, caption_vertical_margin_percent=0.24, caption_bold=False, **common)),
        CaptionPreset(id="gaming-pop", name="Gaming Pop", built_in=True, settings=_settings(caption_font_name="Arial Black", caption_font_size=76, caption_outline_width=4, caption_shadow_depth=3, caption_vertical_margin_percent=0.3, caption_bold=True, caption_animation="pop", **common, **animated)),
        CaptionPreset(id="karaoke-highlight", name="Karaoke Highlight", built_in=True, settings=_settings(caption_font_name="Arial Black", caption_font_size=70, caption_outline_width=3, caption_shadow_depth=2, caption_vertical_margin_percent=0.28, caption_bold=True, caption_animation="karaoke", **common, **animated)),
        CaptionPreset(id="smooth-fade", name="Smooth Fade", built_in=True, settings=_settings(caption_font_name="Arial", caption_font_size=64, caption_outline_width=3, caption_shadow_depth=2, caption_vertical_margin_percent=0.28, caption_bold=True, caption_animation="fade", **common, **animated)),
    ]


def _custom() -> list[CaptionPreset]:
    payload = read_json(PRESETS_PATH) or {}
    values = payload.get("presets", []) if isinstance(payload, dict) else []
    result: list[CaptionPreset] = []
    for value in values:
        try:
            preset = CaptionPreset.model_validate(value)
            if not preset.built_in:
                result.append(preset)
        except Exception:
            continue
    return result


def list_presets() -> list[CaptionPreset]:
    return built_in_presets() + _custom()


def save_preset(request: CaptionPresetRequest, preset_id: str | None = None) -> CaptionPreset:
    if preset_id and preset_id in {preset.id for preset in built_in_presets()}:
        raise ValueError("Built-in presets cannot be changed.")
    preset = CaptionPreset(id=preset_id or f"custom-{uuid.uuid4().hex[:10]}", name=request.name.strip(), settings=request.settings)
    customs = [item for item in _custom() if item.id != preset.id]
    customs.append(preset)
    write_json(PRESETS_PATH, {"version": 1, "presets": [item.model_dump() for item in customs]})
    return preset


def delete_preset(preset_id: str) -> None:
    if preset_id in {preset.id for preset in built_in_presets()}:
        raise ValueError("Built-in presets cannot be deleted.")
    customs = _custom()
    remaining = [item for item in customs if item.id != preset_id]
    if len(remaining) == len(customs):
        raise FileNotFoundError("Caption preset not found.")
    write_json(PRESETS_PATH, {"version": 1, "presets": [item.model_dump() for item in remaining]})