from __future__ import annotations

import math
from typing import Any

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

    @model_validator(mode="after")
    def _validate_render_settings(self) -> "RenderSettings":
        if self.output_width is not None and self.output_width <= 0:
            raise ValueError("Output width must be greater than zero.")
        if self.output_height is not None and self.output_height <= 0:
            raise ValueError("Output height must be greater than zero.")
        if self.fps is not None and (not math.isfinite(self.fps) or self.fps <= 0):
            raise ValueError("FPS must be a positive finite number.")
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
