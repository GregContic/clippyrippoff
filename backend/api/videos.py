from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.schemas import AnalyzeRequest, AnalyzeResponse, ProjectEditorState, VideoListResponse, VideoSummary
from backend.services.analysis_service import start_analysis, start_uploaded_analysis
from backend.services.ingestion import IngestionError, save_uploaded_file, upload_temp_path
from backend.services.job_registry import job_registry
from backend.services.project_service import list_projects, load_editor_state, project_summary, save_editor_state
from scripts.utils import PROCESSING_TEMP_DIR

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=VideoListResponse)
def get_videos(request: Request) -> VideoListResponse:
    return VideoListResponse(items=[VideoSummary(**item) for item in list_projects(owner_id=request.state.user.id)])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_video(request: AnalyzeRequest, http_request: Request) -> AnalyzeResponse:
    try:
        return start_analysis(request.url, force_download=request.force_download, owner_id=http_request.state.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        if "already being analyzed" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.post("/upload", response_model=AnalyzeResponse)
def upload_video(http_request: Request, file: UploadFile = File(...)) -> AnalyzeResponse:
    video_id = f"upload-{uuid4().hex}"
    filename = file.filename or ""
    destination = PROCESSING_TEMP_DIR / "uploads" / video_id / (Path(filename).name or "upload.bin")
    try:
        if file.content_type and not (
            file.content_type.startswith("video/") or file.content_type == "application/octet-stream"
        ):
            raise IngestionError("Upload a video file supported by FFmpeg.")
        destination = upload_temp_path(PROCESSING_TEMP_DIR, video_id, filename)
        save_uploaded_file(file.file, filename, destination)
        return start_uploaded_analysis(
            video_id,
            destination,
            filename=Path(filename).name,
            owner_id=http_request.state.user.id,
        )
    except IngestionError as exc:
        destination.unlink(missing_ok=True)
        status = 413 if "limit" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


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
