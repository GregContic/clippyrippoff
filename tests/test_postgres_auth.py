from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.models import Base, Project, Session as DatabaseSession
from backend.services.auth import AuthRepository, Principal, _now


class TestPostgresAuthentication(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.repository = AuthRepository()
        self.repository_patch = patch("backend.services.auth.auth_repository", self.repository)
        self.factory_patch = patch("backend.services.auth.session_factory", return_value=self.session_factory)
        self.repository_patch.start()
        self.factory_patch.start()
        self.client = TestClient(app)
        self.origin = {"Origin": "http://localhost:5173"}

    def tearDown(self) -> None:
        self.factory_patch.stop()
        self.repository_patch.stop()
        self.engine.dispose()

    def test_registration_and_duplicate_email(self) -> None:
        first = self.client.post(
            "/api/auth/register",
            json={"email": " User@Example.com ", "password": "strong-password-123"},
            headers=self.origin,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["user"]["username"], "user@example.com")

        duplicate = self.client.post(
            "/api/auth/register",
            json={"email": "user@example.com", "password": "another-password-123"},
            headers=self.origin,
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertNotIn("password_hash", duplicate.text)

    def test_login_me_logout_and_failed_login(self) -> None:
        self.repository.register("user@example.com", "strong-password-123")
        failed = self.client.post(
            "/api/auth/login",
            json={"username": "user@example.com", "password": "wrong-password"},
            headers=self.origin,
        )
        self.assertEqual(failed.status_code, 401)

        login = self.client.post(
            "/api/auth/login",
            json={"email": "USER@example.com", "password": "strong-password-123"},
            headers=self.origin,
        )
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("password_hash", login.text)
        csrf = self.client.cookies.get("clippy_csrf")
        self.client.headers.update({"Origin": "http://localhost:5173", "X-CSRF-Token": csrf or ""})
        current = self.client.get("/api/auth/me")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["user"]["username"], "user@example.com")

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_expired_and_revoked_sessions_are_rejected(self) -> None:
        principal = self.repository.register("user@example.com", "strong-password-123")
        token, _ = self.repository.create_session(principal, 300)
        with self.session_factory() as db:
            record = db.query(DatabaseSession).first()
            record.expires_at = _now() - timedelta(seconds=1)
            db.commit()
        self.assertIsNone(self.repository.get_session(token))

        token, _ = self.repository.create_session(principal, 300)
        self.repository.invalidate(token)
        self.assertIsNone(self.repository.get_session(token))

    def test_project_ownership_query_does_not_cross_users(self) -> None:
        first = self.repository.register("first@example.com", "strong-password-123")
        second = self.repository.register("second@example.com", "strong-password-123")
        project_id = uuid4()
        with self.session_factory() as db:
            db.add(Project(id=project_id, user_id=UUID(first.id), name="First project"))
            db.commit()
        self.assertIsNotNone(self.repository.owned_project(first.id, str(project_id)))
        self.assertIsNone(self.repository.owned_project(second.id, str(project_id)))


if __name__ == "__main__":
    unittest.main()
