from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import DatabaseConfigurationError, session_factory
from backend.models import Project, Session as DatabaseSession, User


class AuthenticationError(ValueError):
    pass


class DuplicateEmailError(AuthenticationError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise AuthenticationError("Enter a valid email address.")
    return normalized


def validate_password(password: str) -> str:
    if len(password) < 12:
        raise AuthenticationError("Password must contain at least 12 characters.")
    if len(password) > 1024:
        raise AuthenticationError("Password must not exceed 1024 characters.")
    return password


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    email: str | None = None
    role: str = "user"


class AuthRepository:
    """PostgreSQL auth repository with an explicit filesystem compatibility mode."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        if root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.password_hasher = PasswordHasher()

    @property
    def users_path(self) -> Path:
        if self.root is None:
            raise AuthenticationError("Filesystem authentication is not enabled.")
        return self.root / "users.json"

    @property
    def sessions_path(self) -> Path:
        if self.root is None:
            raise AuthenticationError("Filesystem authentication is not enabled.")
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

    def _db(self) -> Session:
        return session_factory()()

    def _principal(self, user: User) -> Principal:
        return Principal(id=str(user.id), username=user.email, email=user.email, role=user.role)

    def register(self, email: str, password: str) -> Principal:
        normalized_email = normalize_email(email)
        validate_password(password)
        if self.root is not None:
            with self._lock:
                users = self._read(self.users_path)
                if any(item.get("email") == normalized_email for item in users.values() if isinstance(item, dict)):
                    raise DuplicateEmailError("An account with that email already exists.")
                user_id = secrets.token_hex(16)
                users[user_id] = {
                    "id": user_id,
                    "email": normalized_email,
                    "username": normalized_email,
                    "password_hash": self.password_hasher.hash(password),
                    "role": "user",
                }
                self._write(self.users_path, users)
                return Principal(id=user_id, username=normalized_email, email=normalized_email)
        db = self._db()
        try:
            user = User(email=normalized_email, password_hash=self.password_hasher.hash(password), role="user")
            db.add(user)
            db.commit()
            db.refresh(user)
            return self._principal(user)
        except IntegrityError as exc:
            db.rollback()
            raise DuplicateEmailError("An account with that email already exists.") from exc
        finally:
            db.close()

    def bootstrap(self, email: str, password: str) -> Principal:
        validate_password(password)
        if self.root is not None:
            email = email.strip()
            if len(email) < 3 or len(email) > 128:
                raise AuthenticationError("Email must be between 3 and 128 characters.")
            with self._lock:
                users = self._read(self.users_path)
                if users.get("owner") is not None:
                    raise AuthenticationError("The owner account already exists.")
                principal = {"id": secrets.token_hex(16), "username": email, "email": email}
                users["owner"] = {**principal, "password_hash": self.password_hasher.hash(password)}
                self._write(self.users_path, users)
                return Principal(id=principal["id"], username=email, email=email, role="admin")
        normalized_email = normalize_email(email)
        db = self._db()
        try:
            if db.scalar(select(User.id).limit(1)) is not None:
                raise AuthenticationError("An account already exists; bootstrap will not overwrite it.")
            user = User(email=normalized_email, password_hash=self.password_hasher.hash(password), role="admin")
            db.add(user)
            db.commit()
            db.refresh(user)
            return self._principal(user)
        except IntegrityError as exc:
            db.rollback()
            raise DuplicateEmailError("An account with that email already exists.") from exc
        finally:
            db.close()

    def authenticate(self, identifier: str, password: str) -> Principal | None:
        if self.root is not None:
            with self._lock:
                users = self._read(self.users_path)
                records = users.values()
                owner = users.get("owner")
                if isinstance(owner, dict):
                    records = [owner]
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    identity = str(record.get("email") or record.get("username") or "").casefold()
                    if identity != identifier.strip().casefold():
                        continue
                    password_hash = record.get("password_hash")
                    if not isinstance(password_hash, str):
                        return None
                    try:
                        valid = self.password_hasher.verify(password_hash, password)
                    except (VerifyMismatchError, VerificationError, InvalidHashError):
                        return None
                    if valid:
                        return Principal(
                            id=str(record["id"]),
                            username=str(record.get("email") or record.get("username")),
                            email=str(record.get("email") or record.get("username")),
                            role=str(record.get("role", "admin")),
                        )
                return None
        db = self._db()
        try:
            normalized = normalize_email(identifier)
        except AuthenticationError:
            db.close()
            return None
        try:
            user = db.scalar(select(User).where(User.email == normalized, User.is_active.is_(True)))
            if user is None:
                return None
            try:
                valid = self.password_hasher.verify(user.password_hash, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return None
            return self._principal(user) if valid else None
        finally:
            db.close()

    def create_session(self, principal: Principal, ttl_seconds: int) -> tuple[str, str]:
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = _now() + timedelta(seconds=ttl_seconds)
        if self.root is not None:
            with self._lock:
                sessions = self._read(self.sessions_path)
                sessions[_token_hash(session_token)] = {
                    "user_id": principal.id,
                    "username": principal.username,
                    "email": principal.email,
                    "csrf_hash": _token_hash(csrf_token),
                    "expires_at": expires_at.isoformat(),
                }
                self._write(self.sessions_path, sessions)
            return session_token, csrf_token
        db = self._db()
        try:
            db.add(DatabaseSession(
                user_id=UUID(principal.id),
                token_hash=_token_hash(session_token),
                csrf_token_hash=_token_hash(csrf_token),
                expires_at=expires_at,
            ))
            db.commit()
            return session_token, csrf_token
        finally:
            db.close()

    def get_session(self, session_token: str | None) -> tuple[Principal, dict[str, Any]] | None:
        if not session_token:
            return None
        token_hash = _token_hash(session_token)
        if self.root is not None:
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
                principal = Principal(
                    id=str(session["user_id"]),
                    username=str(session.get("email") or session["username"]),
                    email=str(session.get("email") or session["username"]),
                )
                return principal, session
        db = self._db()
        try:
            record = db.scalar(select(DatabaseSession).where(DatabaseSession.token_hash == token_hash))
            if record is None or record.revoked_at is not None or _as_utc(record.expires_at) <= _now():
                return None
            user = db.get(User, record.user_id)
            if user is None or not user.is_active:
                return None
            return self._principal(user), {
                "csrf_hash": record.csrf_token_hash,
                "expires_at": record.expires_at,
            }
        finally:
            db.close()

    def invalidate(self, session_token: str | None) -> None:
        if not session_token:
            return
        token_hash = _token_hash(session_token)
        if self.root is not None:
            with self._lock:
                sessions = self._read(self.sessions_path)
                sessions.pop(token_hash, None)
                self._write(self.sessions_path, sessions)
            return
        db = self._db()
        try:
            record = db.scalar(select(DatabaseSession).where(DatabaseSession.token_hash == token_hash))
            if record is not None:
                record.revoked_at = _now()
                db.commit()
        finally:
            db.close()

    def validate_csrf(self, session: dict[str, Any], csrf_token: str | None) -> bool:
        return bool(csrf_token and secrets.compare_digest(str(session.get("csrf_hash", "")), _token_hash(csrf_token)))

    def owned_project(self, user_id: str, project_id: str) -> Project | None:
        if self.root is not None:
            return None
        db = self._db()
        try:
            return db.scalar(select(Project).where(Project.id == UUID(project_id), Project.user_id == UUID(user_id)))
        finally:
            db.close()


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
    try:
        current = auth_repository.get_session(request.cookies.get(cookie_name()))
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Database authentication is not configured.") from exc
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
    if request.url.path in {"/api/auth/login", "/api/auth/register"}:
        return
    try:
        current = auth_repository.get_session(request.cookies.get(cookie_name()))
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Database authentication is not configured.") from exc
    if current is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    csrf_cookie = request.cookies.get("clippy_csrf")
    csrf_header = request.headers.get("x-csrf-token")
    if not csrf_cookie or csrf_cookie != csrf_header or not auth_repository.validate_csrf(current[1], csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")
