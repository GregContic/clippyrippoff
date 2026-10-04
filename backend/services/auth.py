from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class AuthenticationError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    id: str
    username: str


class AuthRepository:
    """Replaceable persistence boundary for the single-owner account model."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("AUTH_DATA_DIR", "processing/auth"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.password_hasher = PasswordHasher()

    @property
    def users_path(self) -> Path:
        return self.root / "users.json"

    @property
    def sessions_path(self) -> Path:
        return self.root / "sessions.json"

    def _read(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationError(f"Authentication data is unreadable: {path}") from exc
        return payload if isinstance(payload, dict) else {}

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{secrets.token_hex(8)}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)

    def bootstrap(self, username: str, password: str) -> Principal:
        username = username.strip()
        if len(username) < 3 or len(username) > 128:
            raise AuthenticationError("Username must be between 3 and 128 characters.")
        if len(password) < 12:
            raise AuthenticationError("Password must contain at least 12 characters.")
        with self._lock:
            users = self._read(self.users_path)
            if users.get("owner") is not None:
                raise AuthenticationError("The owner account already exists.")
            principal = {"id": secrets.token_hex(16), "username": username}
            users["owner"] = {**principal, "password_hash": self.password_hasher.hash(password)}
            self._write(self.users_path, users)
            return Principal(**principal)

    def authenticate(self, username: str, password: str) -> Principal | None:
        with self._lock:
            owner = self._read(self.users_path).get("owner")
            if not isinstance(owner, dict) or owner.get("username") != username.strip():
                return None
            password_hash = owner.get("password_hash")
            if not isinstance(password_hash, str):
                return None
            try:
                valid = self.password_hasher.verify(password_hash, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return None
            if not valid:
                return None
            return Principal(id=str(owner["id"]), username=str(owner["username"]))

    def create_session(self, principal: Principal, ttl_seconds: int) -> tuple[str, str]:
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = (_now() + timedelta(seconds=ttl_seconds)).isoformat()
        with self._lock:
            sessions = self._read(self.sessions_path)
            sessions[_token_hash(session_token)] = {
                "user_id": principal.id,
                "username": principal.username,
                "csrf_hash": _token_hash(csrf_token),
                "expires_at": expires_at,
            }
            self._write(self.sessions_path, sessions)
        return session_token, csrf_token

    def get_session(self, session_token: str | None) -> tuple[Principal, dict[str, Any]] | None:
        if not session_token:
            return None
        token_hash = _token_hash(session_token)
        with self._lock:
            sessions = self._read(self.sessions_path)
            session = sessions.get(token_hash)
            if not isinstance(session, dict):
                return None
            try:
                expired = datetime.fromisoformat(str(session["expires_at"])) <= _now()
            except (KeyError, TypeError, ValueError):
                expired = True
            if expired:
                sessions.pop(token_hash, None)
                self._write(self.sessions_path, sessions)
                return None
            return Principal(id=str(session["user_id"]), username=str(session["username"])), session

    def invalidate(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self._lock:
            sessions = self._read(self.sessions_path)
            sessions.pop(_token_hash(session_token), None)
            self._write(self.sessions_path, sessions)

    def validate_csrf(self, session: dict[str, Any], csrf_token: str | None) -> bool:
        return bool(csrf_token and secrets.compare_digest(str(session.get("csrf_hash", "")), _token_hash(csrf_token)))


auth_repository = AuthRepository()


def session_ttl_seconds() -> int:
    try:
        value = int(os.getenv("AUTH_SESSION_TTL_SECONDS", "28800"))
    except ValueError as exc:
        raise AuthenticationError("AUTH_SESSION_TTL_SECONDS must be an integer.") from exc
    if not 300 <= value <= 2592000:
        raise AuthenticationError("AUTH_SESSION_TTL_SECONDS must be between 300 and 2592000.")
    return value


def allowed_origins() -> set[str]:
    raw = os.getenv("AUTH_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}
    if not origins:
        raise AuthenticationError("AUTH_ALLOWED_ORIGINS must contain at least one origin.")
    return origins


def secure_cookies() -> bool:
    value = os.getenv("AUTH_COOKIE_SECURE", "false").lower()
    if value not in {"true", "false"}:
        raise AuthenticationError("AUTH_COOKIE_SECURE must be true or false.")
    return value == "true"


def cookie_name() -> str:
    return os.getenv("AUTH_COOKIE_NAME", "clippy_session")


def validate_configuration() -> None:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise AuthenticationError("APP_ENV must be development, test, or production.")
    if environment == "production":
        if not secure_cookies():
            raise AuthenticationError("AUTH_COOKIE_SECURE=true is required in production.")
        if os.getenv("AUTH_DATA_DIR", "processing/auth") == "processing/auth":
            raise AuthenticationError("AUTH_DATA_DIR must point to durable private storage in production.")
        if any("localhost" in origin or "127.0.0.1" in origin for origin in allowed_origins()):
            raise AuthenticationError("Production AUTH_ALLOWED_ORIGINS must not use localhost.")


def get_current_user(request: Request) -> Principal:
    current = auth_repository.get_session(request.cookies.get(cookie_name()))
    if current is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    request.state.user = current[0]
    return current[0]


def csrf_protect(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in allowed_origins():
        raise HTTPException(status_code=403, detail="Invalid request origin.")
    if request.url.path == "/api/auth/login":
        return
    current = auth_repository.get_session(request.cookies.get(cookie_name()))
    if current is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    csrf_cookie = request.cookies.get("clippy_csrf")
    csrf_header = request.headers.get("x-csrf-token")
    if not csrf_cookie or csrf_cookie != csrf_header or not auth_repository.validate_csrf(current[1], csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")
