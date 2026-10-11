import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
import backend.api.videos as videos_api
import backend.services.analysis_service as analysis_service
import backend.services.project_service as project_service
from backend.services.auth import auth_repository
from backend.services.ingestion import IngestionError, save_uploaded_file
from backend.services.job_registry import job_registry
from backend.services.storage import StorageError
import scripts.youtube as youtube


class _Storage:
    def upload_file(self, source, key, content_type=None):
        return None


class _FailingStorage(_Storage):
    def upload_file(self, source, key, content_type=None):
        raise StorageError("storage unavailable")


class TestIngestion(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.cache = self.root / "youtube"
        self.temp = self.root / "temp"
        self.output = self.root / "output"
        self.cache.mkdir()
        self.output.mkdir()
        auth_repository.root = self.root / "auth"
        auth_repository.bootstrap("owner@example.com", "test-password-123")
        self.patches = [
            patch.object(videos_api, "PROCESSING_TEMP_DIR", self.temp),
            patch.object(project_service, "PROJECT_CACHE_DIR", self.cache),
            patch.object(project_service, "PROCESSING_TEMP_DIR", self.temp),
            patch.object(project_service, "OUTPUT_SHORTS_DIR", self.output),
            patch.object(youtube, "YOUTUBE_CACHE_DIR", self.cache),
            patch.object(job_registry, "storage_dir", self.temp / "jobs"),
        ]
        for patcher in self.patches:
            patcher.start()
        job_registry.reset()
        self.client = TestClient(app)
        login = self.client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "test-password-123"},
            headers={"Origin": "http://localhost:5173"},
        )
        self.assertEqual(login.status_code, 200)
        self.client.headers.update(
            {"Origin": "http://localhost:5173", "X-CSRF-Token": self.client.cookies.get("clippy_csrf")}
        )

    def tearDown(self):
        job_registry.reset()
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tempdir.cleanup()

    def _wait(self, job_id):
        deadline = time.time() + 3
        while time.time() < deadline:
            record = job_registry.get(job_id)
            if record is not None and record.status in {"completed", "failed"}:
                return record
            time.sleep(0.01)
        self.fail("ingestion job did not finish")

    def test_invalid_upload_is_rejected(self):
        response = self.client.post(
            "/api/videos/upload",
            files={"file": ("notes.txt", io.BytesIO(b"not video"), "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.json()["detail"].lower())

    def test_upload_size_limit_and_storage_failure(self):
        with patch.dict("os.environ", {"MAX_UPLOAD_BYTES": "4"}):
            response = self.client.post(
                "/api/videos/upload",
                files={"file": ("clip.mp4", io.BytesIO(b"12345"), "video/mp4")},
            )
        self.assertEqual(response.status_code, 413)

        with patch.object(analysis_service, "storage", _FailingStorage()), patch.object(
            analysis_service, "detect_candidates", return_value=[]
        ):
            response = self.client.post(
                "/api/videos/upload",
                files={"file": ("clip.mp4", io.BytesIO(b"fake video"), "video/mp4")},
            )
            record = self._wait(response.json()["job_id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(record.status, "failed")
        self.assertIn("durable storage", record.error)

    def test_uploaded_file_runs_through_analysis(self):
        with patch.object(analysis_service, "storage", _Storage()), patch.object(
            analysis_service, "detect_candidates", return_value=[]
        ):
            response = self.client.post(
                "/api/videos/upload",
                files={"file": ("clip.mp4", io.BytesIO(b"fake video"), "video/mp4")},
            )
            self.assertEqual(response.status_code, 200)
            record = self._wait(response.json()["job_id"])
        self.assertEqual(record.status, "completed")
        metadata = project_service.load_project_metadata(response.json()["video_id"])
        self.assertEqual(metadata["owner_id"], auth_repository.authenticate("owner@example.com", "test-password-123").id)
        self.assertEqual(metadata["status"], "completed")

    def test_uploaded_project_is_not_visible_to_another_user(self):
        project_service.save_project_metadata(
            "upload-owned-project",
            {"owner_id": auth_repository.authenticate("owner@example.com", "test-password-123").id, "status": "completed"},
        )
        registered = self.client.post(
            "/api/auth/register",
            json={"email": "other@example.com", "password": "test-password-456"},
        )
        self.assertEqual(registered.status_code, 201)
        self.client.post("/api/auth/logout")
        login = self.client.post(
            "/api/auth/login",
            json={"email": "other@example.com", "password": "test-password-456"},
            headers={"Origin": "http://localhost:5173"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get("/api/videos/upload-owned-project").status_code, 404)


class TestYouTubeRetryClassification(unittest.TestCase):
    def test_rate_limit_retries_once_with_backoff(self):
        calls = []

        class Downloader:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=True):
                calls.append(url)
                if len(calls) == 1:
                    raise RuntimeError("HTTP Error 429: Too Many Requests")
                output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"video")
                return {"title": "Test"}

        with tempfile.TemporaryDirectory() as directory, patch.object(
            youtube, "_load_yt_dlp", return_value=type("M", (), {"YoutubeDL": Downloader})
        ), patch.object(youtube.time, "sleep") as sleep:
            result = youtube.download_youtube_video(
                "https://youtu.be/abc123XYZ_1", output_dir=Path(directory), force_download=True
            )
        self.assertFalse(result["cached"])
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()

    def test_bot_challenge_does_not_retry(self):
        calls = []

        class Downloader:
            def __init__(self, options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=True):
                calls.append(url)
                raise RuntimeError("Sign in to confirm you're not a bot")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            youtube, "_load_yt_dlp", return_value=type("M", (), {"YoutubeDL": Downloader})
        ), patch.object(youtube.time, "sleep") as sleep:
            with self.assertRaises(youtube.YouTubeBotChallengeError):
                youtube.download_youtube_video(
                    "https://youtu.be/abc123XYZ_1", output_dir=Path(directory), force_download=True
                )
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_network_failure_is_bounded(self):
        calls = []

        class Downloader:
            def __init__(self, options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=True):
                calls.append(url)
                raise TimeoutError("request timed out")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            youtube, "_load_yt_dlp", return_value=type("M", (), {"YoutubeDL": Downloader})
        ), patch.object(youtube.time, "sleep"):
            with self.assertRaises(youtube.YouTubeNetworkError):
                youtube.download_youtube_video(
                    "https://youtu.be/abc123XYZ_1", output_dir=Path(directory), force_download=True
                )
        self.assertEqual(len(calls), 2)

    def test_upload_file_rejects_empty_and_reports_disk_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "clip.mp4"
            with self.assertRaises(IngestionError):
                save_uploaded_file(io.BytesIO(), "clip.mp4", destination)
            with patch("backend.services.ingestion.shutil.disk_usage", side_effect=OSError("disk")):
                with self.assertRaises(IngestionError):
                    save_uploaded_file(io.BytesIO(b"video"), "clip.mp4", destination)


if __name__ == "__main__":
    unittest.main()
