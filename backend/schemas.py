from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class RenderResponse(BaseModel):
    video_id: str
    render_job_ids: list[str]


class JobResponse(BaseModel):
    id: str
    kind: str
    video_id: str | None = None
    candidate_id: int | None = None
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


class CandidateListResponse(BaseModel):
    video_id: str
    candidates: list[CandidateResponse]
    candidate_count: int


class VideoSummary(BaseModel):
    video_id: str
    title: str | None = None
    url: str | None = None
    status: str
    analysis_stage: str | None = None
    message: str | None = None
    candidate_count: int = 0
    rendered_count: int = 0
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
