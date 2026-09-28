from __future__ import annotations

from fastapi import APIRouter

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.schemas import SettingsResponse
from scripts.utils import load_config

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    config = load_config()
    return SettingsResponse(
        whisper_model=str(config.get("whisper_model", "base")),
        clip_min_seconds=float(config.get("clip_min_seconds", 10)),
        clip_max_seconds=float(config.get("clip_max_seconds", 60)),
        max_candidates=int(config.get("max_candidates", 20)),
        context_before_seconds=float(config.get("context_before_seconds", 5)),
        context_after_seconds=float(config.get("context_after_seconds", 8)),
        candidate_merge_gap_seconds=float(config.get("candidate_merge_gap_seconds", 3)),
        boundary_continuation_gap_seconds=float(config.get("boundary_continuation_gap_seconds", 1.5)),
        boundary_quiet_seconds=float(config.get("boundary_quiet_seconds", 1.5)),
        boundary_scene_transition_threshold=float(config.get("boundary_scene_transition_threshold", 0.28)),
    )
