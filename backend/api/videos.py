from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import AnalyzeRequest, AnalyzeResponse, ProjectEditorState, VideoListResponse, VideoSummary
from backend.services.analysis_service import start_analysis
from backend.services.job_registry import job_registry
from backend.services.project_service import list_projects, load_editor_state, project_summary, save_editor_state

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=VideoListResponse)
def get_videos() -> VideoListResponse:
    return VideoListResponse(items=[VideoSummary(**item) for item in list_projects()])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_video(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return start_analysis(request.url, force_download=request.force_download)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        if "already being analyzed" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.get("/{video_id}", response_model=VideoSummary)
def get_video(video_id: str) -> VideoSummary:
    try:
        summary = project_summary(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="Video project not found.")
    return VideoSummary(**summary)


@router.get("/{video_id}/job")
def get_video_job(video_id: str) -> dict:
    for record in job_registry.list():
        if record.video_id == video_id and record.kind == "analysis":
            return record.to_dict()
    raise HTTPException(status_code=404, detail="Analysis job not found.")


@router.get("/{video_id}/editor-state", response_model=ProjectEditorState)
def get_video_editor_state(video_id: str) -> ProjectEditorState:
    payload = load_editor_state(video_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Editor state not found.")
    return ProjectEditorState(**payload)


@router.put("/{video_id}/editor-state", response_model=ProjectEditorState)
def update_video_editor_state(video_id: str, request: ProjectEditorState) -> ProjectEditorState:
    if request.video_id != video_id:
        raise HTTPException(status_code=400, detail="Editor state video_id does not match the route.")
    payload = save_editor_state(video_id, request.model_dump())
    return ProjectEditorState(**payload)
