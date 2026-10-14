from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile

from backend.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ProjectEditorState,
    UploadCompleteRequest,
    UploadConfigResponse,
    UploadStartRequest,
    UploadStartResponse,
    VideoListResponse,
    VideoSummary,
)
from backend.services.analysis_service import start_analysis, start_uploaded_analysis
from backend.services.direct_upload import (
    UploadServiceError,
    cancel_upload,
    complete_upload,
    local_upload_configuration,
    part_upload_url,
    single_upload_url,
    start_upload,
    upload_configuration,
)
from backend.services.ingestion import IngestionError, save_uploaded_file, upload_temp_path
from backend.services.job_registry import job_registry
from backend.services.project_service import list_projects, load_editor_state, project_summary, save_editor_state
from backend.services.storage import S3Storage, storage
from scripts.youtube import YouTubeBotChallengeError, YouTubeRateLimitError
from scripts.utils import PROCESSING_TEMP_DIR

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _upload_error(exc: UploadServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _cleanup_temporary_upload(destination: Path) -> None:
    destination.unlink(missing_ok=True)
    try:
        destination.parent.rmdir()
    except OSError:
        pass


@router.get("", response_model=VideoListResponse)
def get_videos(request: Request) -> VideoListResponse:
    return VideoListResponse(items=[VideoSummary(**item) for item in list_projects(owner_id=request.state.user.id)])


@router.get("/upload/config", response_model=UploadConfigResponse)
def get_upload_config() -> UploadConfigResponse:
    try:
        config = upload_configuration() if isinstance(storage, S3Storage) else local_upload_configuration()
        return UploadConfigResponse(**config)
    except (UploadServiceError, IngestionError) as exc:
        if isinstance(exc, UploadServiceError):
            raise _upload_error(exc) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/uploads", response_model=UploadStartResponse)
def create_upload(request: UploadStartRequest, http_request: Request) -> UploadStartResponse:
    try:
        return UploadStartResponse(
            **start_upload(
                request.filename,
                request.size_bytes,
                request.content_type,
                http_request.state.user.id,
            )
        )
    except UploadServiceError as exc:
        raise _upload_error(exc) from exc


@router.post("/uploads/{upload_id}/url")
def refresh_single_upload_url(upload_id: str, request: Request) -> dict[str, str]:
    try:
        return {"url": single_upload_url(upload_id, request.state.user.id)}
    except UploadServiceError as exc:
        raise _upload_error(exc) from exc


@router.post("/uploads/{upload_id}/parts/{part_number}/url")
def get_upload_part_url(upload_id: str, part_number: int, request: Request) -> dict[str, str]:
    try:
        return {"url": part_upload_url(upload_id, request.state.user.id, part_number)}
    except UploadServiceError as exc:
        raise _upload_error(exc) from exc


@router.post("/uploads/{upload_id}/complete", response_model=AnalyzeResponse)
def finish_upload(upload_id: str, body: UploadCompleteRequest, request: Request) -> AnalyzeResponse:
    try:
        result = complete_upload(
            upload_id,
            request.state.user.id,
            [part.model_dump() for part in body.parts],
        )
        return AnalyzeResponse(**result)
    except UploadServiceError as exc:
        raise _upload_error(exc) from exc


@router.delete("/uploads/{upload_id}", status_code=204, response_class=Response)
def remove_upload(upload_id: str, request: Request) -> Response:
    try:
        cancel_upload(upload_id, request.state.user.id)
    except UploadServiceError as exc:
        raise _upload_error(exc) from exc
    return Response(status_code=204)


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_video(request: AnalyzeRequest, http_request: Request) -> AnalyzeResponse:
    try:
        return start_analysis(request.url, force_download=request.force_download, owner_id=http_request.state.user.id)
    except (YouTubeRateLimitError, YouTubeBotChallengeError) as exc:
        retry_after = max(1, int(exc.retry_after_seconds or 1))
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(retry_after)},
        ) from exc
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
        _cleanup_temporary_upload(destination)
        status = 413 if "limit" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception:
        _cleanup_temporary_upload(destination)
        raise


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
