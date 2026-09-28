from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.api.candidates import router as candidates_router
from backend.api.library import router as library_router
from backend.api.renders import router as renders_router
from backend.api.settings import router as settings_router
from backend.api.videos import router as videos_router
from scripts.utils import OUTPUT_SHORTS_DIR, PROCESSING_TEMP_DIR, ensure_directories

app = FastAPI(title="ClippyRipoff API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos_router)
app.include_router(candidates_router)
app.include_router(renders_router)
app.include_router(library_router)
app.include_router(settings_router)


@app.on_event("startup")
def _startup() -> None:
    ensure_directories()


app.mount(
    "/media/shorts",
    StaticFiles(directory=OUTPUT_SHORTS_DIR, check_dir=False),
    name="shorts",
)
app.mount(
    "/media/cache",
    StaticFiles(directory=PROCESSING_TEMP_DIR / "youtube", check_dir=False),
    name="cache",
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
