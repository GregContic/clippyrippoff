from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.api.candidates import router as candidates_router
from backend.api.caption_presets import router as caption_presets_router
from backend.api.library import router as library_router
from backend.api.media import router as media_router
from backend.api.auth import router as auth_router
from backend.api.projects import router as projects_router
from backend.api.renders import router as renders_router
from backend.api.settings import router as settings_router
from backend.api.videos import router as videos_router
from backend.services.job_registry import job_registry
from backend.services.auth import allowed_origins, csrf_protect, get_current_user, validate_configuration
from scripts.utils import ensure_directories

app = FastAPI(title="ClippyRipoff API", version="1.0.0")
validate_configuration()

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins()),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    try:
        csrf_protect(request)
    except Exception as exc:
        if hasattr(exc, "status_code"):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        raise
    return await call_next(request)

protected_dependency = [Depends(get_current_user)]
app.include_router(videos_router, dependencies=protected_dependency)
app.include_router(projects_router, dependencies=protected_dependency)
app.include_router(candidates_router, dependencies=protected_dependency)
app.include_router(caption_presets_router, dependencies=protected_dependency)
app.include_router(renders_router, dependencies=protected_dependency)
app.include_router(library_router, dependencies=protected_dependency)
app.include_router(media_router, dependencies=protected_dependency)
app.include_router(settings_router, dependencies=protected_dependency)
app.include_router(auth_router)


@app.on_event("startup")
def _startup() -> None:
    ensure_directories()
    job_registry.restore_from_disk()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
