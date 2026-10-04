from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


def _user_payload(principal) -> dict[str, str]:
    return {"id": principal.id, "username": principal.username}


@router.post("/login")
def login(request: Request, response: Response, payload: LoginRequest) -> dict:
    if request.headers.get("origin", "").rstrip("/") not in auth_service.allowed_origins():
        raise HTTPException(status_code=403, detail="Invalid request origin.")
    principal = auth_service.auth_repository.authenticate(payload.username, payload.password)
    if principal is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    session_token, csrf_token = auth_service.auth_repository.create_session(principal, auth_service.session_ttl_seconds())
    flags = {"httponly": True, "secure": auth_service.secure_cookies(), "samesite": "lax", "path": "/"}
    response.set_cookie(auth_service.cookie_name(), session_token, max_age=auth_service.session_ttl_seconds(), **flags)
    response.set_cookie("clippy_csrf", csrf_token, max_age=auth_service.session_ttl_seconds(), httponly=False, **{key: value for key, value in flags.items() if key != "httponly"})
    return {"user": _user_payload(principal)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    auth_service.auth_repository.invalidate(request.cookies.get(auth_service.cookie_name()))
    response.delete_cookie(auth_service.cookie_name(), path="/")
    response.delete_cookie("clippy_csrf", path="/")
    return {"status": "logged_out"}


@router.get("/me")
def me(request: Request) -> dict:
    current = auth_service.auth_repository.get_session(request.cookies.get(auth_service.cookie_name()))
    if current is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return {"user": _user_payload(current[0])}
