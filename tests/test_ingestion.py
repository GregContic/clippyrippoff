import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
import backend.api.media as media_api
import backend.api.videos as videos_api
import backend.services.analysis_service as analysis_service
import backend.services.compilation_service as compilation_service
import backend.services.project_service as project_service
import backend.services.render_service as render_service
from backend.services.auth import auth_repository
from backend.services.ingestion import IngestionError, save_uploaded_file
from backend.services.job_registry import job_registry
from backend.services.storage import StorageError
import scripts.youtube as youtube


class _Storage:
    def __init__(self):
        self.objects = {}

    def upload_file(self, source, key, content_type=None):
        self.objects[key] = Path(source).read_bytes()

    def download_file(self, key, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def exists(self, key):
        return key in self.objects

    def open_stream(self, key):
        return io.BytesIO(self.objects[key])


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
        youtube._DOWNLOAD_LOCKS.clear()
        youtube._EXTRACTION_COOLDOWNS.clear()
        auth_repository.root = self.root / "auth"
        auth_repository.bootstrap("owner@example.com", "test-password-123")
        self.patches = [
            patch.object(videos_api, "PROCESSING_TEMP_DIR", self.temp),
            patch.object(analysis_service, "PROCESSING_TEMP_DIR", self.temp),
            patch.object(project_service, "PROJECT_CACHE_DIR", self.cache),
            patch.object(project_service, "PROCESSING_TEMP_DIR", self.temp),
            patch.object(project_service, "OUTPUT_SHORTS_DIR", self.output),
            patch.object(
                project_service,
                "get_media_info",
                return_value={"duration": 12.0, "has_video": True, "has_audio": True},
            ),
            patch.object(render_service, "OUTPUT_SHORTS_DIR", self.output),
            patch.object(render_service, "PROCESSING_TEMP_DIR", self.root),
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

    def _temporary_upload_files(self):
        upload_root = self.temp / "uploads"
        return [path for path in upload_root.rglob("*") if path.is_file()] if upload_root.exists() else []

    def _authenticated_client(self, *, raise_server_exceptions=True):
        client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
        login = client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "test-password-123"},
            headers={"Origin": "http://localhost:5173"},
        )
        self.assertEqual(login.status_code, 200)
        client.headers.update(
            {
                "Origin": "http://localhost:5173",
                "X-CSRF-Token": client.cookies.get("clippy_csrf"),
            }
        )
        return client

    def test_invalid_upload_is_rejected(self):
        response = self.client.post(
            "/api/videos/upload",
            files={"file": ("notes.txt", io.BytesIO(b"not video"), "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.json()["detail"].lower())
        self.assertEqual(self._temporary_upload_files(), [])

    def test_multipart_form_upload_rejects_empty_file_and_cleans_temporary_path(self):
        response = self.client.post(
            "/api/videos/upload",
            files={"file": ("clip.mp4", io.BytesIO(), "video/mp4")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.json()["detail"].lower())
        self.assertEqual(self._temporary_upload_files(), [])

    def test_multipart_form_upload_rejects_bad_mime_extension_and_path(self):
        bad_mime = self.client.post(
            "/api/videos/upload",
            files={"file": ("clip.mp4", io.BytesIO(b"video"), "text/plain")},
        )
        bad_extension = self.client.post(
            "/api/videos/upload",
            files={"file": ("notes.txt", io.BytesIO(b"video"), "application/octet-stream")},
        )
        path_traversal = self.client.post(
            "/api/videos/upload",
            files={"file": ("../clip.mp4", io.BytesIO(b"video"), "video/mp4")},
        )

        self.assertEqual(bad_mime.status_code, 400)
        self.assertEqual(bad_extension.status_code, 400)
        self.assertEqual(path_traversal.status_code, 400)
        self.assertEqual(self._temporary_upload_files(), [])

    def test_multipart_form_upload_rejects_malformed_request(self):
        missing = self.client.post("/api/videos/upload")
        wrong_field = self.client.post(
            "/api/videos/upload",
            files={"video": ("clip.mp4", io.BytesIO(b"video"), "video/mp4")},
        )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(wrong_field.status_code, 422)
        self.assertEqual(self._temporary_upload_files(), [])

    def test_multipart_form_upload_cleans_file_when_analysis_startup_raises(self):
        client = self._authenticated_client(raise_server_exceptions=False)
        try:
            with patch.object(
                videos_api,
                "start_uploaded_analysis",
                side_effect=RuntimeError("analysis startup failed"),
            ):
                response = client.post(
                    "/api/videos/upload",
                    files={"file": ("clip.mp4", io.BytesIO(b"video"), "video/mp4")},
                )
        finally:
            client.close()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._temporary_upload_files(), [])

    def test_upload_size_limit_and_storage_failure(self):
        with patch.dict("os.environ", {"MAX_UPLOAD_BYTES": "4"}):
            response = self.client.post(
                "/api/videos/upload",
                files={"file": ("clip.mp4", io.BytesIO(b"12345"), "video/mp4")},
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self._temporary_upload_files(), [])

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
        self.assertEqual(self._temporary_upload_files(), [])

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
        self.assertEqual(self._temporary_upload_files(), [])

    def test_stored_r2_upload_uses_existing_analysis_pipeline_and_cleans_temporary_source(self):
        video_id = "upload-1234567890abcdef1234567890abcdef"
        source_key = "uploads/pending/test-id/clip.mp4"
        source_store = _Storage()
        source_store.objects[source_key] = b"fake video"
        with patch.object(analysis_service, "storage", source_store), patch.object(
            analysis_service, "detect_candidates", return_value=[]
        ):
            response = analysis_service.start_stored_upload_analysis(
                video_id,
                source_key,
                filename="clip.mp4",
                owner_id="owner-id",
                size_bytes=len(source_store.objects[source_key]),
            )
            record = self._wait(response.job_id)

        self.assertEqual(record.status, "completed")
        metadata = project_service.load_project_metadata(video_id)
        self.assertEqual(metadata["source_storage_key"], source_key)
        self.assertEqual(metadata["owner_id"], "owner-id")
        self.assertFalse(
            Path(metadata["source_path"]).exists(),
            f"temporary source was not removed: {metadata['source_path']}",
        )

    def test_uploaded_file_can_generate_candidates_and_render_a_clip(self):
        storage = _Storage()
        candidate = {
            "id": 1,
            "start": 0.0,
            "end": 12.0,
            "duration": 12.0,
            "candidate_score": 80,
            "transcript": "Uploaded clip",
            "signals": {},
            "audio_peak": 0.5,
            "relative_audio_peak": 2.0,
            "audio_level": "MEDIUM",
            "reaction_detected": True,
            "matched_keywords": [],
            "scene_change_score": 0.2,
            "trigger_time": 6.0,
            "trigger_types": ["upload"],
        }

        def render_short(_source, _start, _end, _config, _ass, output, progress_callback=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"rendered clip")

        def detect_candidates(_source, _config, transcript_path):
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript_path.write_text(
                '{"source":"clip.mp4","segments":[]}',
                encoding="utf-8",
            )
            return [candidate]

        with patch.object(analysis_service, "storage", storage), patch.object(
            render_service, "storage", storage
        ), patch.object(
            compilation_service, "storage", storage
        ), patch.object(
            compilation_service, "PROCESSING_TEMP_DIR", self.root
        ), patch.object(
            media_api, "storage", storage
        ), patch.object(
            analysis_service, "detect_candidates", side_effect=detect_candidates
        ), patch.object(
            render_service, "get_media_info", return_value={"duration": 12.0, "has_audio": True}
        ), patch.object(
            render_service, "build_caption_cues", return_value=[]
        ), patch.object(
            render_service, "render_short", side_effect=render_short
        ), patch.object(
            render_service, "verify_output", return_value=[]
        ):
            response = self.client.post(
                "/api/videos/upload",
                files={"file": ("clip.mp4", io.BytesIO(b"fake video"), "video/mp4")},
            )
            analysis = self._wait(response.json()["job_id"])
            candidates = self.client.get(
                f"/api/videos/{response.json()['video_id']}/candidates"
            )
            metadata = project_service.load_project_metadata(response.json()["video_id"])
            source_path = Path(metadata["source_path"])
            source_path.unlink()
            preview = self.client.get(candidates.json()["candidates"][0]["preview_url"])
            render = self.client.post(
                f"/api/videos/{response.json()['video_id']}/render",
                json={"candidate_ids": [1]},
            )
            rendered = self._wait(render.json()["render_job_ids"][0])
            source_path.unlink()
            compilation_source = compilation_service._resolve_source(
                response.json()["video_id"],
                metadata,
            )
            compilation_bytes = compilation_source.read_bytes()
            compilation_source.unlink()
            batch_preflight = render_service.submit_renders(
                response.json()["video_id"],
                [1],
                overrides={1: {"start": 0.0, "end": 12.0}},
                preflight_only=True,
                owner_id=metadata["owner_id"],
            )
            batch_source_restored = source_path.is_file()

        self.assertEqual(analysis.status, "completed")
        self.assertEqual(candidates.status_code, 200)
        self.assertEqual(candidates.json()["candidates"][0]["id"], 1)
        self.assertIsNotNone(candidates.json()["candidates"][0]["preview_url"])
        self.assertEqual(candidates.json()["source_duration"], 12.0)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, b"fake video")
        self.assertEqual(render.status_code, 200)
        self.assertEqual(rendered.status, "completed", rendered.error)
        self.assertTrue(rendered.output_url.startswith("/api/media/artifacts/"))
        self.assertEqual(compilation_bytes, b"fake video")
        self.assertEqual(batch_preflight, [])
        self.assertTrue(batch_source_restored)

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
    def setUp(self):
        youtube._DOWNLOAD_LOCKS.clear()
        youtube._EXTRACTION_COOLDOWNS.clear()

    def test_rate_limit_stops_immediately_and_enforces_cooldown(self):
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
                raise RuntimeError("HTTP Error 429: Too Many Requests")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            youtube, "_load_yt_dlp", return_value=type("M", (), {"YoutubeDL": Downloader})
        ), patch.object(youtube.time, "sleep") as sleep, patch.object(
            youtube.time, "monotonic", return_value=100.0
        ):
            with self.assertRaises(youtube.YouTubeRateLimitError):
                youtube.download_youtube_video(
                    "https://youtu.be/abc123XYZ_1",
                    output_dir=Path(directory),
                    force_download=True,
                )
            with self.assertRaises(youtube.YouTubeRateLimitError) as cooldown:
                youtube.download_youtube_video(
                    "https://youtu.be/abc123XYZ_1",
                    output_dir=Path(directory),
                    force_download=True,
                )
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            cooldown.exception.retry_after_seconds,
            youtube.RATE_LIMIT_COOLDOWN_SECONDS,
        )
        sleep.assert_not_called()

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
        ), patch.object(youtube.time, "sleep") as sleep, patch.object(
            youtube.random, "uniform", side_effect=[0.1, 0.2]
        ):
            with self.assertRaises(youtube.YouTubeNetworkError):
                youtube.download_youtube_video(
                    "https://youtu.be/abc123XYZ_1", output_dir=Path(directory), force_download=True
                )
        self.assertEqual(len(calls), youtube.NETWORK_MAX_ATTEMPTS)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [1.1, 2.2],
        )

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
