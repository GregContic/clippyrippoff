import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.auth import AuthRepository


class TestAuthentication(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        repository = AuthRepository(Path(self.tempdir.name))
        self.repository_patch = patch("backend.services.auth.auth_repository", repository)
        self.repository_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.repository_patch.stop()
        self.tempdir.cleanup()

    def test_password_hashing_and_login(self):
        repository = __import__("backend.services.auth", fromlist=["auth_repository"]).auth_repository
        repository.bootstrap("owner", "strong-password-123")
        self.assertIsNone(repository.authenticate("owner", "wrong-password"))
        response = self.client.post("/api/auth/login", json={"username": "owner", "password": "strong-password-123"}, headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("password", response.text)
        self.assertNotIn("password_hash", response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])

    def test_protected_routes_require_session(self):
        protected_paths = [
            "/api/videos",
            "/api/projects",
            "/api/videos/abc123XYZ_1/candidates",
            "/api/caption-presets",
            "/api/renders",
            "/api/library",
            "/api/settings",
            "/api/media/shorts/missing.mp4",
        ]
        for path in protected_paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_session_persists_and_logout_invalidates(self):
        repository = __import__("backend.services.auth", fromlist=["auth_repository"]).auth_repository
        repository.bootstrap("owner", "strong-password-123")
        login = self.client.post("/api/auth/login", json={"username": "owner", "password": "strong-password-123"}, headers={"Origin": "http://localhost:5173"})
        self.assertEqual(login.status_code, 200)
        self.client.headers.update({"Origin": "http://localhost:5173", "X-CSRF-Token": self.client.cookies.get("clippy_csrf")})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_csrf_rejects_state_change_without_matching_token(self):
        repository = __import__("backend.services.auth", fromlist=["auth_repository"]).auth_repository
        repository.bootstrap("owner", "strong-password-123")
        self.client.post("/api/auth/login", json={"username": "owner", "password": "strong-password-123"}, headers={"Origin": "http://localhost:5173"})
        response = self.client.post("/api/auth/logout", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 403)
