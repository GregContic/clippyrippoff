from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import JobResponse, ProjectFilesResponse, VideoListResponse, VideoSummary
from backend.services.project_service import list_projects, project_files, project_render_jobs, project_summary

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=VideoListResponse)
def get_projects() -> VideoListResponse:
    return VideoListResponse(items=[VideoSummary(**item) for item in list_projects()])


@router.get("/{video_id}", response_model=VideoSummary)
def get_project(video_id: str) -> VideoSummary:
    try:
        summary = project_summary(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if summary is None:
      raise HTTPException(status_code=404, detail="Project not found.")
    return VideoSummary(**summary)


@router.get("/{video_id}/summary", response_model=VideoSummary)
def get_project_summary(video_id: str) -> VideoSummary:
    try:
        summary = project_summary(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return VideoSummary(**summary)


@router.get("/{video_id}/renders", response_model=list[JobResponse])
def get_project_renders(video_id: str) -> list[JobResponse]:
    try:
        summary = project_summary(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return [JobResponse(**item) for item in project_render_jobs(video_id)]


@router.get("/{video_id}/files", response_model=ProjectFilesResponse)
def get_project_files(video_id: str) -> ProjectFilesResponse:
    try:
        summary = project_summary(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return ProjectFilesResponse(items=project_files(video_id))