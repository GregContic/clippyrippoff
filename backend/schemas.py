from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TrimBounds(BaseModel):
    start: float
    end: float

    @model_validator(mode="after")
    def _validate_bounds(self) -> "TrimBounds":
        if not math.isfinite(self.start):
            raise ValueError("Trim start must be a finite number.")
        if not math.isfinite(self.end):
            raise ValueError("Trim end must be a finite number.")
        if self.end <= self.start:
            raise ValueError("Trim end must be after trim start.")
        return self


class CaptionSegmentEdit(BaseModel):
    start: float
    end: float
    text: str

    @model_validator(mode="after")
    def _validate_segment(self) -> "CaptionSegmentEdit":
        if not math.isfinite(self.start):
            raise ValueError("Caption segment start must be a finite number.")
        if not math.isfinite(self.end):
            raise ValueError("Caption segment end must be a finite number.")
        if self.end <= self.start:
            raise ValueError("Caption segment end must be after its start.")
        return self


class RenderSettings(BaseModel):
    output_width: int | None = None
    output_height: int | None = None
    fps: float | None = None
    captions_enabled: bool | None = None
    normalize_audio: bool | None = None
    caption_font_name: str | None = None
    caption_font_size: int | None = None
    caption_primary_color: str | None = None
    caption_outline_color: str | None = None
    caption_shadow_color: str | None = None
    caption_outline_width: int | None = None
    caption_shadow_depth: int | None = None
    caption_vertical_margin_percent: float | None = None
    caption_bold: bool | None = None
    caption_preset_id: str | None = None
    caption_animation: Literal["none", "pop", "karaoke", "fade"] = "none"
    caption_animation_duration: float = 0.16
    caption_highlight_color: str = "&H0000FFFF"

    @model_validator(mode="after")
    def _validate_render_settings(self) -> "RenderSettings":
        if self.output_width is not None and self.output_width <= 0:
            raise ValueError("Output width must be greater than zero.")
        if self.output_height is not None and self.output_height <= 0:
            raise ValueError("Output height must be greater than zero.")
        if self.fps is not None and (not math.isfinite(self.fps) or self.fps <= 0):
            raise ValueError("FPS must be a positive finite number.")
        if self.caption_font_name is not None and self.caption_font_name not in {"Arial", "Arial Black", "DejaVu Sans", "Liberation Sans", "Verdana"}:
            raise ValueError("Caption font is not supported.")
        if self.caption_font_size is not None and not 16 <= self.caption_font_size <= 180:
            raise ValueError("Caption font size must be between 16 and 180.")
        for name in ("caption_primary_color", "caption_outline_color", "caption_shadow_color"):
            value = getattr(self, name)
            if value is not None and not re.fullmatch(r"&H[0-9A-Fa-f]{8}", value):
                raise ValueError(f"{name} must be an 8-digit ASS color.")
        if self.caption_highlight_color is not None and not re.fullmatch(r"&H[0-9A-Fa-f]{8}", self.caption_highlight_color):
            raise ValueError("caption_highlight_color must be an 8-digit ASS color.")
        if self.caption_animation_duration is not None and (not math.isfinite(self.caption_animation_duration) or not 0.02 <= self.caption_animation_duration <= 0.8):
            raise ValueError("Caption animation duration must be between 0.02 and 0.8 seconds.")
        if self.caption_outline_width is not None and not 0 <= self.caption_outline_width <= 20:
            raise ValueError("Caption outline width must be between 0 and 20.")
        if self.caption_shadow_depth is not None and not 0 <= self.caption_shadow_depth <= 20:
            raise ValueError("Caption shadow depth must be between 0 and 20.")
        if self.caption_vertical_margin_percent is not None and not 0.05 <= self.caption_vertical_margin_percent <= 0.8:
            raise ValueError("Caption vertical margin must be between 0.05 and 0.8.")
        return self


class CandidateEditorState(BaseModel):
    trim: TrimBounds | None = None
    caption_segments: list[CaptionSegmentEdit] = Field(default_factory=list)
    render_settings: RenderSettings = Field(default_factory=RenderSettings)
    selected: bool = False


class ProjectEditorState(BaseModel):
    video_id: str
    selected_candidate_id: int | None = None
    candidates: dict[str, CandidateEditorState] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    url: str
    force_download: bool = False


class AnalyzeResponse(BaseModel):
    video_id: str
    status: str
    job_id: str | None = None
    title: str | None = None
    analysis_stage: str | None = None
    message: str | None = None
    candidate_count: int = 0
    rendered_count: int = 0


class RenderRequest(BaseModel):
    candidate_ids: list[int] = Field(default_factory=list)
    overrides: dict[str, TrimBounds] = Field(default_factory=dict)
    candidate_states: dict[str, CandidateEditorState] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    status: Literal["pending_review", "approved", "needs_changes"]
    notes: str = ""


class CaptionPreset(BaseModel):
    id: str
    name: str
    built_in: bool = False
    version: int = 1
    settings: RenderSettings


class CaptionPresetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    settings: RenderSettings


class RenderResponse(BaseModel):
    video_id: str
    render_job_ids: list[str]


class JobResponse(BaseModel):
    id: str
    kind: str
    video_id: str | None = None
    candidate_id: int | None = None
    retry_of: str | None = None
    status: str
    stage: str | None = None
    message: str | None = None
    percent: float | None = None
    error: str | None = None
    output_path: str | None = None
    output_url: str | None = None
    result: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    review_status: str = "pending_review"
    review_notes: str = ""


class CandidateResponse(BaseModel):
    id: int
    start: float
    end: float
    duration: float
    candidate_score: int
    transcript: str | None = None
    signals: dict[str, Any]
    audio_peak: float
    relative_audio_peak: float
    audio_level: str
    reaction_detected: bool
    matched_keywords: list[str]
    scene_change_score: float
    trigger_time: float | None = None
    trigger_types: list[str]
    start_reason: str | None = None
    end_reason: str | None = None
    setup_seconds: float | None = None
    payoff_seconds: float | None = None
    preview_url: str | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    trim_saved: bool = False


class CandidateListResponse(BaseModel):
    video_id: str
    source_duration: float | None = None
    candidates: list[CandidateResponse]
    candidate_count: int


class VideoSummary(BaseModel):
    video_id: str
    title: str | None = None
    url: str | None = None
    source_thumbnail_url: str | None = None
    status: str
    analysis_stage: str | None = None
    message: str | None = None
    candidate_count: int = 0
    rendered_count: int = 0
    source_duration: float | None = None
    source_cache_status: str | None = None
    project_created_at: str | None = None
    last_analyzed_at: str | None = None
    latest_activity_at: str | None = None
    saved_editing_state: bool = False
    manual_trim_count: int = 0
    render_job_count: int = 0
    queued_render_jobs: int = 0
    running_render_jobs: int = 0
    completed_render_jobs: int = 0
    failed_render_jobs: int = 0
    interrupted_render_jobs: int = 0
    generated_output_count: int = 0
    source_url: str | None = None
    source_video_url: str | None = None
    transcript_url: str | None = None
    candidates_url: str | None = None
    rendered_urls: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    analysis_job_id: str | None = None


class VideoListResponse(BaseModel):
    items: list[VideoSummary]


class ProjectFileItem(BaseModel):
    filename: str
    url: str
    size_bytes: int
    created_at: str | None = None
    duration: float | None = None
    candidate_id: int | None = None
    render_job_id: str | None = None


class ProjectFilesResponse(BaseModel):
    items: list[ProjectFileItem]


class LibraryItem(BaseModel):
    filename: str
    url: str
    size_bytes: int
    created_at: str | None = None
    duration: float | None = None
    review_status: str = "pending_review"
    render_job_id: str | None = None


class LibraryResponse(BaseModel):
    items: list[LibraryItem]


class SettingsResponse(BaseModel):
    whisper_model: str
    clip_min_seconds: float
    clip_max_seconds: float
    max_candidates: int
    context_before_seconds: float | None = None
    context_after_seconds: float | None = None
    candidate_merge_gap_seconds: float | None = None
    boundary_continuation_gap_seconds: float | None = None
    boundary_quiet_seconds: float | None = None
    boundary_scene_transition_threshold: float | None = None
