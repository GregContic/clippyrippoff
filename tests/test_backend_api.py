import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, Lock
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
import backend.api.videos as videos_api
import backend.services.analysis_service as analysis_service
import backend.services.compilation_service as compilation_service
import backend.api.videos as videos_api
import backend.services.direct_upload as direct_upload
import backend.services.project_service as project_service
import backend.services.render_service as render_service
import backend.api.media as media_api
import backend.services.batch_service as batch_service
from backend.services.job_registry import job_registry
from backend.services.auth import auth_repository
from backend.services.storage import S3Storage, StorageError, StorageSettings
from scripts.youtube import (
    BOT_CHALLENGE_MESSAGE,
    RATE_LIMIT_MESSAGE,
    YouTubeBotChallengeError,
    YouTubeRateLimitError,
    YouTubeUnavailableError,
)
from tests.test_direct_upload import _R2Client


class TestBackendApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.cache_root = self.root / "processing" / "temp" / "youtube"
        self.output_root = self.root / "output" / "shorts"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        auth_repository.root = self.root / "auth"
        auth_repository.root.mkdir(parents=True, exist_ok=True)
        auth_repository.bootstrap("owner", "test-password-123")

        self.patches = [
            patch.object(project_service, "PROJECT_CACHE_DIR", self.cache_root),
            patch.object(project_service, "OUTPUT_SHORTS_DIR", self.output_root),
            patch.object(project_service, "PROCESSING_TEMP_DIR", self.root / "processing" / "temp"),
            patch.object(render_service, "OUTPUT_SHORTS_DIR", self.output_root),
            patch.object(media_api, "OUTPUT_SHORTS_DIR", self.output_root),
            patch.object(render_service, "PROCESSING_TEMP_DIR", self.root / "processing" / "temp"),
            patch.object(compilation_service, "OUTPUT_SHORTS_DIR", self.output_root),
            patch.object(compilation_service, "PROCESSING_TEMP_DIR", self.root / "processing" / "temp"),
            patch.object(analysis_service, "_YOUTUBE_SOURCE_CACHE_DIR", self.root / "processing" / "temp" / "youtube_sources"),
            patch.object(job_registry, "storage_dir", self.root / "processing" / "temp" / "render_jobs"),
            patch.object(project_service, "get_media_info", return_value={"duration": 60.5}),
            patch.object(render_service, "get_media_info", return_value={"duration": 60.5}),
            patch.object(render_service, "build_caption_cues", return_value=[]),
        ]
        for patcher in self.patches:
            patcher.start()

        job_registry.reset()

        self.client = TestClient(app)
        login = self.client.post("/api/auth/login", json={"username": "owner", "password": "test-password-123"}, headers={"Origin": "http://localhost:5173"})
        self.assertEqual(login.status_code, 200)
        self.owner_id = login.json()["user"]["id"]
        self.client.headers.update({"Origin": "http://localhost:5173", "X-CSRF-Token": self.client.cookies.get("clippy_csrf")})

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        job_registry.reset()
        self.tempdir.cleanup()

    def _create_project(self, video_id: str = "abc123XYZ_1", owner_id: str | None = None) -> Path:
        owner_id = self.owner_id if owner_id is None else owner_id
        project_dir = self.cache_root / video_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "video_id": video_id,
                    "url": f"https://youtu.be/{video_id}",
                    "title": "Test Video",
                    "status": "completed",
                    "analysis_stage": "complete",
                    "message": "Complete",
                    "candidate_count": 1,
                    "rendered_count": 0,
                    "source_path": str(project_dir / "source.mp4"),
                    **({"owner_id": owner_id} if owner_id is not None else {}),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (project_dir / "candidates.json").write_text(
            json.dumps(
                {
                    "source": "source.mp4",
                    "source_type": "youtube",
                    "source_url": f"https://youtu.be/{video_id}",
                    "video_id": video_id,
                    "title": "Test Video",
                    "candidates": [
                        {
                            "id": 1,
                            "start": 12.0,
                            "end": 24.0,
                            "duration": 12.0,
                            "candidate_score": 82,
                            "transcript": "No way",
                            "signals": {"transcript_score": 30},
                            "audio_peak": 0.5,
                            "relative_audio_peak": 2.2,
                            "audio_level": "MEDIUM",
                            "reaction_detected": True,
                            "matched_keywords": ["no way"],
                            "scene_change_score": 0.3,
                            "trigger_time": 18.0,
                            "trigger_types": ["reaction", "audio_peak"],
                            "start_reason": "trigger_context",
                            "end_reason": "quiet_boundary",
                            "setup_seconds": 6.0,
                            "payoff_seconds": 6.0,
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (project_dir / "transcript.json").write_text(
            json.dumps(
                {
                    "source": "source.mp4",
                    "segments": [
                        {"start": 12.0, "end": 24.0, "text": "This is a test clip."},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (project_dir / "source.mp4").write_bytes(b"fake-video")
        return project_dir

    def _authenticated_client(self, email: str, password: str) -> TestClient:
        auth_repository.register(email, password)
        client = TestClient(app)
        login = client.post(
            "/api/auth/login",
            json={"username": email, "password": password},
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

    @staticmethod
    def _wait_for(condition, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("Condition was not met before timeout.")

    @staticmethod
    def _wait_for_job_completion(job_id: str, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = job_registry.get(job_id)
            if record is not None and record.status in {"completed", "failed"}:
                return
            time.sleep(0.01)
        raise AssertionError("Render job did not finish before timeout.")

    def test_invalid_youtube_url_is_rejected(self) -> None:
        response = self.client.post("/api/videos/analyze", json={"url": "https://example.com/watch?v=abc"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid YouTube URL", response.json()["detail"])

    def test_direct_upload_start_endpoint_returns_presigned_contract(self) -> None:
        payload = {
            "upload_id": "a" * 32,
            "video_id": "upload-" + "b" * 32,
            "upload_mode": "multipart",
            "upload_url": None,
            "part_size_bytes": 5 * 1024 * 1024,
        }
        with patch.object(videos_api, "start_upload", return_value=payload) as start:
            response = self.client.post(
                "/api/videos/uploads",
                json={"filename": "clip.mp4", "size_bytes": 6 * 1024 * 1024, "content_type": "video/mp4"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        start.assert_called_once_with("clip.mp4", 6 * 1024 * 1024, "video/mp4", self.owner_id)

    def test_direct_upload_endpoints_validate_input_and_isolate_ownership_errors(self) -> None:
        malformed = self.client.post(
            "/api/videos/uploads",
            json={"filename": "clip.mp4", "size_bytes": 0, "content_type": "video/mp4"},
        )
        self.assertEqual(malformed.status_code, 422)

        with patch.object(
            videos_api,
            "start_upload",
            side_effect=videos_api.UploadServiceError(413, "Upload exceeds the 20 MB limit."),
        ):
            oversized = self.client.post(
                "/api/videos/uploads",
                json={"filename": "clip.mp4", "size_bytes": 21 * 1024 * 1024, "content_type": "video/mp4"},
            )
        self.assertEqual(oversized.status_code, 413)
        self.assertIn("20 MB", oversized.json()["detail"])

        with patch.object(
            videos_api,
            "single_upload_url",
            side_effect=videos_api.UploadServiceError(404, "Upload session not found."),
        ):
            wrong_owner = self.client.post("/api/videos/uploads/" + "c" * 32 + "/url")
        self.assertEqual(wrong_owner.status_code, 404)
        self.assertEqual(wrong_owner.json()["detail"], "Upload session not found.")

    def test_multipart_url_completion_and_cancel_endpoints_use_expected_contracts(self) -> None:
        upload_id = "d" * 32
        with patch.object(videos_api, "part_upload_url", return_value="https://r2.example/part") as part_url:
            response = self.client.post(f"/api/videos/uploads/{upload_id}/parts/2/url")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://r2.example/part"})

        completion = {"video_id": "upload-" + "e" * 32, "status": "queued", "job_id": "job-upload"}
        with patch.object(videos_api, "complete_upload", return_value=completion) as complete:
            response = self.client.post(
                f"/api/videos/uploads/{upload_id}/complete",
                json={"parts": [{"part_number": 1, "etag": "etag-1"}, {"part_number": 2, "etag": "etag-2"}]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job_id"], "job-upload")
        complete.assert_called_once_with(
            upload_id,
            self.owner_id,
            [{"part_number": 1, "etag": "etag-1"}, {"part_number": 2, "etag": "etag-2"}],
        )

        with patch.object(videos_api, "cancel_upload") as cancel:
            response = self.client.delete(f"/api/videos/uploads/{upload_id}")
        self.assertEqual(response.status_code, 204)
        cancel.assert_called_once_with(upload_id, self.owner_id)

    def test_direct_upload_requires_authentication_and_is_owner_scoped(self) -> None:
        backend = S3Storage(
            StorageSettings("r2", self.root / "temp", "private", "endpoint", "access", "secret"),
            client=_R2Client(),
        )
        with patch.object(direct_upload, "storage", backend), patch.object(videos_api, "storage", backend):
            unauthenticated = TestClient(app).post(
                "/api/videos/uploads",
                json={"filename": "clip.mp4", "size_bytes": 8, "content_type": "video/mp4"},
                headers={"Origin": "http://localhost:5173"},
            )
            self.assertEqual(unauthenticated.status_code, 401)

            response = self.client.post(
                "/api/videos/uploads",
                json={"filename": "clip.mp4", "size_bytes": 8, "content_type": "video/mp4"},
            )
            self.assertEqual(response.status_code, 200)
            upload_id = response.json()["upload_id"]

            other_user = self._authenticated_client("other@example.com", "test-password-123")
            denied = other_user.delete(f"/api/videos/uploads/{upload_id}")
            self.assertEqual(denied.status_code, 404)

            canceled = self.client.delete(f"/api/videos/uploads/{upload_id}")
            self.assertEqual(canceled.status_code, 204)

    def test_bot_challenge_marks_analysis_job_and_project_failed(self) -> None:
        fixed_now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        with patch.object(
            analysis_service,
            "download_youtube_video",
            side_effect=YouTubeBotChallengeError(BOT_CHALLENGE_MESSAGE),
        ), patch.object(
            analysis_service,
            "_utcnow",
            return_value=fixed_now,
        ):
            response = self.client.post(
                "/api/videos/analyze",
                json={"url": "https://youtu.be/abc123XYZ_1"},
            )
            self.assertEqual(response.status_code, 200)
            project_id = response.json()["video_id"]
            job_id = response.json()["job_id"]
            self._wait_for_job_completion(job_id)
            retry_response = self.client.post(
                "/api/videos/analyze",
                json={"url": "https://youtu.be/abc123XYZ_1"},
            )

        job_response = self.client.get(f"/api/videos/{project_id}/job")
        project_response = self.client.get(f"/api/videos/{project_id}")
        self.assertEqual(job_response.status_code, 200)
        self.assertEqual(job_response.json()["status"], "failed")
        self.assertEqual(job_response.json()["stage"], "failed")
        self.assertIn(BOT_CHALLENGE_MESSAGE, job_response.json()["message"])
        self.assertIn("Retry after", job_response.json()["error"])
        self.assertEqual(
            job_response.json()["result"]["failure_code"],
            "youtube_bot_challenge",
        )
        self.assertEqual(
            job_response.json()["result"]["retry_after"],
            "2026-10-13T12:15:00+00:00",
        )
        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(project_response.json()["status"], "failed")
        self.assertEqual(project_response.json()["analysis_stage"], "failed")
        self.assertIn(BOT_CHALLENGE_MESSAGE, project_response.json()["message"])
        self.assertEqual(project_response.json()["failure_code"], "youtube_bot_challenge")
        self.assertEqual(
            project_response.json()["retry_after"],
            "2026-10-13T12:15:00+00:00",
        )
        self.assertEqual(project_response.json()["retry_after_seconds"], 900)
        self.assertEqual(retry_response.status_code, 429)
        self.assertEqual(retry_response.headers["Retry-After"], "900")
        self.assertIn("Upload video", retry_response.json()["detail"])
        self.assertEqual(
            len([job for job in job_registry.list() if job.kind == "analysis"]),
            1,
        )

    def test_rate_limit_persists_retry_after_and_blocks_duplicate_job(self) -> None:
        fixed_now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        with patch.object(
            analysis_service,
            "download_youtube_video",
            side_effect=YouTubeRateLimitError(RATE_LIMIT_MESSAGE),
        ), patch.object(
            analysis_service,
            "_utcnow",
            return_value=fixed_now,
        ):
            response = self.client.post(
                "/api/videos/analyze",
                json={"url": "https://youtu.be/abc123XYZ_1"},
            )
            self.assertEqual(response.status_code, 200)
            project_id = response.json()["video_id"]
            self._wait_for_job_completion(response.json()["job_id"])
            retry_response = self.client.post(
                "/api/videos/analyze",
                json={"url": "https://youtu.be/abc123XYZ_1"},
            )

        project_response = self.client.get(f"/api/videos/{project_id}")
        self.assertEqual(project_response.json()["failure_code"], "youtube_rate_limited")
        self.assertEqual(
            project_response.json()["retry_after"],
            "2026-10-13T12:05:00+00:00",
        )
        self.assertEqual(project_response.json()["retry_after_seconds"], 300)
        self.assertEqual(retry_response.status_code, 429)
        self.assertEqual(retry_response.headers["Retry-After"], "300")
        self.assertEqual(
            len([job for job in job_registry.list() if job.kind == "analysis"]),
            1,
        )

    def test_completed_youtube_project_is_reused_only_by_its_owner(self) -> None:
        url = "https://youtu.be/abc123XYZ_1"
        owner_project_id = project_service.youtube_project_id(url, self.owner_id)
        project_dir = self._create_project(owner_project_id)
        metadata_path = project_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["url"] = url
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        other_client = self._authenticated_client("other@example.com", "test-password-123")

        with patch.object(
            analysis_service,
            "download_youtube_video",
            side_effect=YouTubeUnavailableError("Unavailable in test."),
        ) as downloader:
            owner_response = self.client.post("/api/videos/analyze", json={"url": url})
            other_response = other_client.post("/api/videos/analyze", json={"url": url})
            self._wait_for_job_completion(other_response.json()["job_id"])

        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(owner_response.json()["status"], "completed")
        self.assertEqual(owner_response.json()["video_id"], owner_project_id)
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(other_response.json()["status"], "queued")
        self.assertNotEqual(other_response.json()["video_id"], owner_project_id)
        self.assertEqual(downloader.call_count, 1)
        self.assertEqual(other_client.get(f"/api/videos/{owner_project_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/videos/{other_response.json()['video_id']}").status_code, 404)

    def test_youtube_cooldown_is_reused_only_by_its_owner(self) -> None:
        url = "https://youtu.be/cooldnXYZ_1"
        fixed_now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        owner_project_id = project_service.youtube_project_id(url, self.owner_id)
        project_dir = self._create_project(owner_project_id)
        metadata_path = project_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.update(
            {
                "url": url,
                "status": "failed",
                "analysis_stage": "failed",
                "message": "Owner-only cooldown",
                "failure_code": YouTubeRateLimitError.failure_code,
                "retry_after": "2026-10-13T12:05:00+00:00",
                "retry_after_seconds": 300,
            }
        )
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        other_client = self._authenticated_client("cooldown-other@example.com", "test-password-123")

        with patch.object(analysis_service, "_utcnow", return_value=fixed_now), patch.object(
            analysis_service,
            "download_youtube_video",
            side_effect=YouTubeUnavailableError("Unavailable in test."),
        ):
            owner_response = self.client.post("/api/videos/analyze", json={"url": url})
            other_response = other_client.post("/api/videos/analyze", json={"url": url})
            self._wait_for_job_completion(other_response.json()["job_id"])

        self.assertEqual(owner_response.status_code, 429)
        self.assertEqual(owner_response.headers["Retry-After"], "300")
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(other_response.json()["status"], "queued")
        self.assertNotEqual(other_response.json()["video_id"], owner_project_id)
        self.assertNotIn("Owner-only cooldown", other_response.text)
        self.assertEqual(other_client.get(f"/api/videos/{owner_project_id}").status_code, 404)

    def test_concurrent_users_get_distinct_active_youtube_projects(self) -> None:
        url = "https://youtu.be/activeXYZ_1"
        other_client = self._authenticated_client("active-other@example.com", "test-password-123")
        downloads_started = Event()
        release_downloads = Event()
        counter_lock = Lock()
        download_count = 0

        def blocked_download(*args, **kwargs):
            nonlocal download_count
            with counter_lock:
                download_count += 1
                if download_count == 2:
                    downloads_started.set()
            release_downloads.wait(2)
            raise YouTubeUnavailableError("Unavailable in test.")

        try:
            with patch.object(analysis_service, "download_youtube_video", side_effect=blocked_download):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    owner_future = executor.submit(self.client.post, "/api/videos/analyze", json={"url": url})
                    other_future = executor.submit(other_client.post, "/api/videos/analyze", json={"url": url})
                    owner_response = owner_future.result(timeout=2)
                    other_response = other_future.result(timeout=2)
                    self.assertTrue(downloads_started.wait(2))

                self.assertEqual(owner_response.status_code, 200)
                self.assertEqual(other_response.status_code, 200)
                self.assertEqual(owner_response.json()["status"], "queued")
                self.assertEqual(other_response.json()["status"], "queued")
                self.assertNotEqual(owner_response.json()["video_id"], other_response.json()["video_id"])
                self.assertNotEqual(owner_response.json()["job_id"], other_response.json()["job_id"])
                self.assertEqual(other_client.get(f"/api/videos/{owner_response.json()['video_id']}").status_code, 404)
                self.assertEqual(self.client.get(f"/api/videos/{other_response.json()['video_id']}").status_code, 404)
        finally:
            release_downloads.set()

        self._wait_for_job_completion(owner_response.json()["job_id"])
        self._wait_for_job_completion(other_response.json()["job_id"])

    def test_unowned_legacy_youtube_project_is_not_reused(self) -> None:
        url = "https://youtu.be/legacyXYZ_1"
        legacy_dir = self._create_project("legacyXYZ_1")
        metadata_path = legacy_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.pop("owner_id", None)
        metadata["url"] = url
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with patch.object(
            analysis_service,
            "download_youtube_video",
            side_effect=YouTubeUnavailableError("Unavailable in test."),
        ):
            response = self.client.post("/api/videos/analyze", json={"url": url})
            self._wait_for_job_completion(response.json()["job_id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")
        self.assertNotEqual(response.json()["video_id"], "legacyXYZ_1")
        self.assertEqual(
            json.loads(metadata_path.read_text(encoding="utf-8")).get("owner_id"),
            None,
        )

    def test_owned_legacy_youtube_project_remains_reusable_by_its_owner(self) -> None:
        url = "https://youtu.be/ownedLegacy_1"
        legacy_dir = self._create_project("ownedLegacy_1")
        metadata_path = legacy_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["url"] = url
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with patch.object(analysis_service, "download_youtube_video") as downloader:
            response = self.client.post("/api/videos/analyze", json={"url": url})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(response.json()["video_id"], "ownedLegacy_1")
        downloader.assert_not_called()

    def test_candidate_retrieval_returns_cached_candidates(self) -> None:
        self._create_project()
        response = self.client.get("/api/videos/abc123XYZ_1/candidates")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["id"], 1)
        self.assertIsNotNone(payload["candidates"][0]["preview_url"])

    def test_project_summary_generates_and_exposes_cached_thumbnail(self) -> None:
        project_dir = self._create_project()

        def fake_thumbnail_command(args, description):
            Path(args[-1]).write_bytes(b"thumbnail")

        with patch.object(project_service, "run_subprocess", side_effect=fake_thumbnail_command):
            response = self.client.get("/api/projects/abc123XYZ_1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_thumbnail_url"], "/media/cache/abc123XYZ_1/thumbnail.jpg")
        self.assertTrue((project_dir / "thumbnail.jpg").exists())

        second_response = self.client.get("/api/projects/abc123XYZ_1")
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["source_thumbnail_url"], "/media/cache/abc123XYZ_1/thumbnail.jpg")

    def test_project_listing_and_details_include_workspace_summary(self) -> None:
        self._create_project()
        save_response = self.client.put(
            "/api/videos/abc123XYZ_1/candidates/1/trim",
            json={"start": 14.0, "end": 26.0},
        )
        self.assertEqual(save_response.status_code, 200)

        list_response = self.client.get("/api/projects")
        self.assertEqual(list_response.status_code, 200)
        project = list_response.json()["items"][0]
        self.assertEqual(project["video_id"], "abc123XYZ_1")
        self.assertEqual(project["source_cache_status"], "available")
        self.assertGreaterEqual(project["manual_trim_count"], 1)
        self.assertIn("latest_activity_at", project)

        detail_response = self.client.get("/api/projects/abc123XYZ_1")
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()
        self.assertEqual(detail["video_id"], "abc123XYZ_1")
        self.assertEqual(detail["candidate_count"], 1)
        self.assertEqual(detail["source_cache_status"], "available")

    def test_project_render_and_file_routes_are_scoped_to_the_project(self) -> None:
        self._create_project()

        def fake_render_short(source_path, start, end, config, ass_path, output_path, progress_callback=None):
            output_path.write_bytes(b"rendered")

        with patch.object(render_service, "render_short", side_effect=fake_render_short), patch.object(render_service, "verify_output", return_value=[]):
            response = self.client.post("/api/videos/abc123XYZ_1/render", json={"candidate_ids": [1]})
            self.assertEqual(response.status_code, 200)
            self._wait_for_job_completion(response.json()["render_job_ids"][0])

        renders_response = self.client.get("/api/projects/abc123XYZ_1/renders")
        self.assertEqual(renders_response.status_code, 200)
        self.assertTrue(all(job["video_id"] == "abc123XYZ_1" for job in renders_response.json()))

        files_response = self.client.get("/api/projects/abc123XYZ_1/files")
        self.assertEqual(files_response.status_code, 200)
        file_payload = files_response.json()["items"]
        self.assertEqual(len(file_payload), 1)
        self.assertEqual(file_payload[0]["candidate_id"], 1)

    def test_malformed_project_metadata_is_ignored_in_project_listing(self) -> None:
        bad_project = self.cache_root / "bad-project"
        bad_project.mkdir(parents=True, exist_ok=True)
        (bad_project / "metadata.json").write_text("not-json", encoding="utf-8")

        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    def test_missing_candidate_collection_returns_404(self) -> None:
        response = self.client.get("/api/videos/missing/candidates")
        self.assertEqual(response.status_code, 404)
        self.assertIn("No candidates", response.json()["detail"])

    def test_render_request_validation_rejects_missing_or_unknown_candidates(self) -> None:
        self._create_project()
        empty_response = self.client.post("/api/videos/abc123XYZ_1/render", json={"candidate_ids": []})
        self.assertEqual(empty_response.status_code, 400)
        missing_response = self.client.post("/api/videos/abc123XYZ_1/render", json={"candidate_ids": [99]})
        self.assertEqual(missing_response.status_code, 404)

    def test_duplicate_analysis_request_returns_existing_project_when_already_completed(self) -> None:
        self._create_project()
        response = self.client.post("/api/videos/analyze", json={"url": "https://youtu.be/abc123XYZ_1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["video_id"], "abc123XYZ_1")
        self.assertIsNone(payload["job_id"])

    def test_duplicate_queued_analysis_request_is_rejected(self) -> None:
        project_service.save_project_metadata(
            "abc123XYZ_1",
            {
                "video_id": "abc123XYZ_1",
                "url": "https://youtu.be/abc123XYZ_1",
                "owner_id": self.owner_id,
                "status": "queued",
                "analysis_stage": "queued",
                "message": "Queued",
            },
        )
        duplicate = self.client.post(
            "/api/videos/analyze",
            json={"url": "https://youtu.be/abc123XYZ_1"},
        )

        self.assertEqual(duplicate.status_code, 409)
        self.assertFalse([job for job in job_registry.list() if job.kind == "analysis"])

    def test_manual_trim_save_does_not_change_candidate_json(self) -> None:
        self._create_project()
        project_dir = self.cache_root / "abc123XYZ_1"
        candidates_path = project_dir / "candidates.json"
        original = candidates_path.read_text(encoding="utf-8")

        response = self.client.put(
            "/api/videos/abc123XYZ_1/candidates/1/trim",
            json={"start": 14.0, "end": 26.0},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(candidates_path.read_text(encoding="utf-8"), original)
        self.assertTrue((project_dir / "manual_trims.json").exists())

    def test_editor_state_round_trips_for_candidate(self) -> None:
        self._create_project()
        response = self.client.put(
            "/api/videos/abc123XYZ_1/editor-state",
            json={
                "video_id": "abc123XYZ_1",
                "selected_candidate_id": 1,
                "candidates": {
                    "1": {
                        "trim": {"start": 14.0, "end": 26.0},
                        "caption_segments": [{"start": 14.0, "end": 16.0, "text": "Edited caption"}],
                        "render_settings": {"output_width": 720, "output_height": 1280, "fps": 24, "captions_enabled": False, "normalize_audio": False, "caption_animation": "fade", "caption_animation_duration": 0.2},
                        "selected": True,
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 200)

        get_response = self.client.get("/api/videos/abc123XYZ_1/editor-state")
        self.assertEqual(get_response.status_code, 200)
        payload = get_response.json()
        self.assertEqual(payload["selected_candidate_id"], 1)
        self.assertEqual(payload["candidates"]["1"]["trim"]["start"], 14.0)
        self.assertEqual(payload["candidates"]["1"]["caption_segments"][0]["text"], "Edited caption")

    def test_render_with_manual_override_passes_selected_values_to_renderer(self) -> None:
        self._create_project()
        captured: list[tuple[float, float, str | None]] = []

        def fake_render_short(source_path, start, end, config, ass_path, output_path, progress_callback=None):
            captured.append((start, end, str(ass_path) if ass_path is not None else None))
            output_path.write_bytes(b"rendered")

        with patch.object(render_service, "render_short", side_effect=fake_render_short), patch.object(render_service, "verify_output", return_value=[]):
            response = self.client.post(
                "/api/videos/abc123XYZ_1/render",
                json={"candidate_ids": [1], "overrides": {"1": {"start": 14.0, "end": 26.0}}},
            )

            self.assertEqual(response.status_code, 200)
            self._wait_for(lambda: bool(captured))
            self._wait_for_job_completion(response.json()["render_job_ids"][0])
            self.assertEqual(captured[0][0], 14.0)
            self.assertEqual(captured[0][1], 26.0)

    def test_render_uses_editor_state_snapshot_for_captions_and_settings(self) -> None:
        self._create_project()
        captured: list[tuple[dict, str | None, float, float]] = []

        def fake_render_short(source_path, start, end, config, ass_path, output_path, progress_callback=None):
            captured.append((config, str(ass_path) if ass_path is not None else None, start, end))
            output_path.write_bytes(b"rendered")

        editor_response = self.client.put(
            "/api/videos/abc123XYZ_1/editor-state",
            json={
                "video_id": "abc123XYZ_1",
                "selected_candidate_id": 1,
                "candidates": {
                    "1": {
                        "trim": {"start": 14.0, "end": 26.0},
                        "caption_segments": [{"start": 14.0, "end": 16.0, "text": "Edited caption"}],
                        "render_settings": {"output_width": 720, "output_height": 1280, "fps": 24, "captions_enabled": False, "normalize_audio": False, "caption_animation": "fade", "caption_animation_duration": 0.2},
                        "selected": True,
                    }
                },
            },
        )
        self.assertEqual(editor_response.status_code, 200)
        self.assertEqual(editor_response.json()["candidates"]["1"]["render_settings"]["caption_animation"], "fade")

        with patch.object(render_service, "render_short", side_effect=fake_render_short), patch.object(render_service, "verify_output", return_value=[]):
            response = self.client.post("/api/videos/abc123XYZ_1/render", json={"candidate_ids": [1]})

            self.assertEqual(response.status_code, 200)
            self._wait_for(lambda: bool(captured))
            self._wait_for_job_completion(response.json()["render_job_ids"][0])

        config, ass_path, start, end = captured[0]
        self.assertEqual((start, end), (14.0, 26.0))
        self.assertEqual(config["output_width"], 720)
        self.assertEqual(config["output_height"], 1280)
        self.assertEqual(config["fps"], 24)
        self.assertFalse(config["normalize_audio"])
        self.assertEqual(config["caption_animation"], "fade")
        self.assertEqual(config["caption_animation_duration"], 0.2)
        self.assertIsNone(ass_path)
        snapshot = job_registry.get(response.json()["render_job_ids"][0]).result["request_signature"]
        self.assertEqual(snapshot["render_settings"]["caption_animation"], "fade")

    def test_render_without_override_keeps_candidate_boundaries(self) -> None:
        self._create_project()
        captured: list[tuple[float, float]] = []

        def fake_render_short(source_path, start, end, config, ass_path, output_path, progress_callback=None):
            captured.append((start, end))
            output_path.write_bytes(b"rendered")

        with patch.object(render_service, "render_short", side_effect=fake_render_short):
            response = self.client.post("/api/videos/abc123XYZ_1/render", json={"candidate_ids": [1]})

            self.assertEqual(response.status_code, 200)
            self._wait_for(lambda: bool(captured))
            self._wait_for_job_completion(response.json()["render_job_ids"][0])
            self.assertEqual(captured[0], (12.0, 24.0))

    def test_running_render_persists_time_based_progress_before_completion(self) -> None:
        self._create_project()
        started = Event()
        release = Event()

        def fake_render_short(source_path, start, end, config, ass_path, output_path, progress_callback=None):
            self.assertIsNotNone(progress_callback)
            progress_callback({"out_time_us": "4200000"})
            started.set()
            release.wait(timeout=2)
            output_path.write_bytes(b"rendered")

        with patch.object(render_service, "render_short", side_effect=fake_render_short), patch.object(render_service, "verify_output", return_value=[]):
            response = self.client.post("/api/videos/abc123XYZ_1/render", json={"candidate_ids": [1]})
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["render_job_ids"][0]
            self.assertTrue(started.wait(timeout=2))
            running = self.client.get(f"/api/renders/{job_id}").json()
            self.assertEqual(running["status"], "running")
            self.assertAlmostEqual(running["percent"], 35.0)
            release.set()
            self._wait_for_job_completion(job_id)

        completed = self.client.get(f"/api/renders/{job_id}").json()
        self.assertEqual(completed["percent"], 100.0)

    def test_render_validation_rejects_invalid_trim_values(self) -> None:
        self._create_project()

        invalid_cases = [
            ({"start": -1.0, "end": 10.0}, 422),
            ({"start": 15.0, "end": 15.0}, 422),
            ({"start": 15.0, "end": 22.0}, 422),
            ({"start": 15.0, "end": 80.0}, 422),
            ({"start": 55.0, "end": 61.0}, 422),
        ]

        for override, expected_status in invalid_cases:
            response = self.client.post(
                "/api/videos/abc123XYZ_1/render",
                json={"candidate_ids": [1], "overrides": {"1": override}},
            )
            self.assertEqual(response.status_code, expected_status)

    def test_render_validation_rejects_non_finite_timestamps(self) -> None:
        self._create_project()
        response = self.client.post(
            "/api/videos/abc123XYZ_1/render",
            json={"candidate_ids": [1], "overrides": {"1": {"start": "nan", "end": 26.0}}},
        )
        self.assertEqual(response.status_code, 422)

    def test_render_validation_rejects_end_beyond_source_duration(self) -> None:
        self._create_project()
        response = self.client.post(
            "/api/videos/abc123XYZ_1/render",
            json={"candidate_ids": [1], "overrides": {"1": {"start": 54.0, "end": 61.0}}},
        )
        self.assertEqual(response.status_code, 422)

    def test_source_candidates_include_manual_trim_state(self) -> None:
        self._create_project()
        save_response = self.client.put(
            "/api/videos/abc123XYZ_1/candidates/1/trim",
            json={"start": 14.0, "end": 26.0},
        )
        self.assertEqual(save_response.status_code, 200)

        candidates_response = self.client.get("/api/videos/abc123XYZ_1/candidates")
        self.assertEqual(candidates_response.status_code, 200)
        candidate = candidates_response.json()["candidates"][0]
        self.assertTrue(candidate["trim_saved"])
        self.assertEqual(candidate["trim_start"], 14.0)
        self.assertEqual(candidate["trim_end"], 26.0)

    def test_library_listing_and_safe_deletion(self) -> None:
        self._create_project("legacy-video")
        short_path = self.output_root / "short_2026-09-27_001.mp4"
        short_path.write_bytes(b"video")
        job = job_registry.create("render", video_id="legacy-video")
        job_registry.update(job.id, status="completed", output_path=str(short_path))

        response = self.client.get("/api/library")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["filename"], short_path.name)

        delete_response = self.client.delete(f"/api/library/{short_path.name}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(short_path.exists())

        with self.assertRaises(ValueError):
            project_service.safe_output_path("..\\evil.mp4")

    def test_library_preserves_projects_and_lists_durable_renders(self) -> None:
        class FakeR2(S3Storage):
            def list_keys(self, prefix: str):
                return iter(
                    [
                        "projects/video-b/renders/short-b.mp4",
                        "projects/video-b/candidates.json",
                    ]
                )

            def object_size(self, key: str) -> int | None:
                return 456

        self._create_project("video-a", owner_id=self.owner_id)
        self._create_project("video-b", owner_id=self.owner_id)
        local_a = self.output_root / "short-a.mp4"
        local_a.write_bytes(b"video-a")
        local_job = job_registry.create("render", video_id="video-a")
        job_registry.update(local_job.id, status="completed", output_path=str(local_a))

        fake_storage = object.__new__(FakeR2)
        with patch.object(project_service, "storage", fake_storage):
            first = self.client.get("/api/library")
            self.assertEqual(first.status_code, 200)
            self.assertEqual({item["filename"] for item in first.json()["items"]}, {"short-a.mp4", "short-b.mp4"})
            self.assertIn("/api/media/renders/video-b/short-b.mp4", {item["url"] for item in first.json()["items"]})

            second = self.client.get("/api/library")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(
                [item["filename"] for item in second.json()["items"]],
                [item["filename"] for item in first.json()["items"]],
            )

        other_client = self._authenticated_client("library-other@example.com", "other-password-123")
        other_response = other_client.get("/api/library")
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(other_response.json()["items"], [])

    def test_library_storage_failure_is_not_reported_as_empty(self) -> None:
        class FailingR2(S3Storage):
            def list_keys(self, prefix: str):
                raise StorageError("R2 listing failed")

        fake_storage = object.__new__(FailingR2)
        with patch.object(project_service, "storage", fake_storage):
            response = self.client.get("/api/library")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Library storage is temporarily unavailable."})

    def test_artifact_media_and_deletion_are_owner_scoped(self) -> None:
        project_dir = self._create_project("artifact-video")
        output = self.output_root / "short-artifact.mp4"
        output.write_bytes(b"artifact")
        metadata_path = project_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["artifacts"] = [{
            "artifact_id": "artifact-owner-only",
            "project_id": "artifact-video",
            "owner_id": self.owner_id,
            "kind": "clip",
            "filename": output.name,
            "status": "completed",
        }]
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        other_client = self._authenticated_client("artifact-other@example.com", "other-password-123")
        self.assertEqual(other_client.get("/api/media/artifacts/artifact-owner-only").status_code, 404)
        self.assertEqual(other_client.delete("/api/library/artifacts/artifact-owner-only").status_code, 404)
        self.assertEqual(self.client.get("/api/media/artifacts/artifact-owner-only").status_code, 200)
        self.assertEqual(self.client.delete("/api/library/artifacts/artifact-owner-only").status_code, 200)
        self.assertFalse(output.exists())

    def test_batch_creation_and_status_are_owner_scoped(self) -> None:
        self._create_project("batch-video")
        child = job_registry.create("render", video_id="batch-video", candidate_id=1, artifact_id="batch-artifact")
        job_registry.update(child.id, status="completed", percent=100.0, output_url="/api/media/artifacts/batch-artifact")
        with patch.object(batch_service, "submit_renders", return_value=[child.id]):
            response = self.client.post(
                "/api/projects/batch-video/batches",
                json={"target_duration_seconds": 30, "minimum_spacing_seconds": 5, "max_clips": 1},
            )
        self.assertEqual(response.status_code, 200)
        batch = response.json()
        self.assertEqual(batch["status"], "completed")
        self.assertEqual(batch["children"][0]["artifact_id"], "batch-artifact")
        self.assertEqual(project_service.load_project_metadata("batch-video")["batches"][0]["batch_id"], batch["batch_id"])
        other_client = self._authenticated_client("batch-other@example.com", "other-password-123")
        self.assertEqual(other_client.get(f"/api/batches/{batch['batch_id']}").status_code, 404)

    def test_smart_editing_rejects_compilation_only_transition_before_job_creation(self) -> None:
        self._create_project("effects-video")
        response = self.client.post(
            "/api/videos/effects-video/render",
            json={
                "candidate_ids": [1],
                "editing": {"schema_version": 1, "transition": "crossfade"},
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("only supported for Auto-Compilation", response.json()["detail"])
        self.assertFalse(any(job.kind == "render" for job in job_registry.list()))

    def test_project_music_endpoints_reject_cross_user_access_and_bad_formats(self) -> None:
        self._create_project("music-project")
        other_client = self._authenticated_client("music-other@example.com", "other-password-123")
        self.assertEqual(other_client.get("/api/projects/music-project/music").status_code, 404)
        denied = other_client.post(
            "/api/projects/music-project/music",
            files={"file": ("track.mp3", b"audio", "audio/mpeg")},
        )
        self.assertEqual(denied.status_code, 404)
        invalid = self.client.post(
            "/api/projects/music-project/music",
            files={"file": ("track.exe", b"not audio", "application/octet-stream")},
        )
        self.assertEqual(invalid.status_code, 422)

    def _wait_for_compilation(self, compilation_id: str, client: TestClient | None = None) -> dict:
        selected_client = client or self.client
        for _ in range(200):
            response = selected_client.get(f"/api/compilations/{compilation_id}")
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            if payload["status"] in {"completed", "failed", "interrupted"}:
                cleanup_dir = self.root / "processing" / "temp" / "compilations" / compilation_id
                for _ in range(100):
                    if not cleanup_dir.exists():
                        break
                    time.sleep(0.01)
                self.assertFalse(cleanup_dir.exists(), "Compilation temporary files were not cleaned.")
                return payload
            time.sleep(0.01)
        self.fail("Compilation did not reach a terminal status.")

    def _compilation_test_patches(self, fake_storage):
        def render_segment(_source, _start, _end, _config, _ass, output, progress_callback=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"normalized segment")

        def concatenate(command, _description):
            Path(command[-1]).write_bytes(b"compiled output")

        return [
            patch.object(
                compilation_service,
                "get_media_info",
                return_value={"duration": 60.5, "has_audio": True},
            ),
            patch.object(
                compilation_service,
                "load_config",
                return_value={
                    "clip_min_seconds": 10,
                    "clip_max_seconds": 60,
                    "output_width": 1080,
                    "output_height": 1920,
                    "fps": 30,
                    "captions_enabled": True,
                },
            ),
            patch.object(compilation_service, "_caption_source", return_value=[]),
            patch.object(compilation_service, "render_short", side_effect=render_segment),
            patch.object(compilation_service, "run_subprocess", side_effect=concatenate),
            patch.object(compilation_service, "verify_compilation_output"),
            patch.object(compilation_service, "storage", fake_storage),
        ]

    def test_compilation_creation_preserves_order_and_persists_unique_artifacts(self) -> None:
        class FakeStorage:
            def __init__(self):
                self.uploaded = []

            def exists(self, _key):
                return False

            def upload_file(self, source, key, content_type=None):
                self.uploaded.append((key, content_type, source.read_bytes()))

        project_dir = self._create_project("compile-project")
        source = project_dir / "source.mp4"
        source.write_bytes(b"source")
        candidates_path = project_dir / "candidates.json"
        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        second = dict(candidates["candidates"][0])
        second.update({"id": 2, "start": 30.0, "end": 42.0})
        candidates["candidates"].append(second)
        candidates_path.write_text(json.dumps(candidates), encoding="utf-8")
        fake_storage = FakeStorage()
        patchers = self._compilation_test_patches(fake_storage)
        for patcher in patchers:
            patcher.start()
        try:
            created = []
            for _ in range(2):
                response = self.client.post(
                    "/api/projects/compile-project/compilations",
                    json={
                        "segments": [{"candidate_id": 2}, {"candidate_id": 1}],
                        "max_total_duration_seconds": 30,
                        "render_settings": {"captions_enabled": False},
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual([segment["candidate_id"] for segment in body["segments"]], [2, 1])
                completed = self._wait_for_compilation(body["compilation_id"])
                self.assertEqual(completed["status"], "completed", completed)
                self.assertEqual(completed["progress"], 100.0)
                self.assertTrue(completed["output_url"].endswith(completed["output_artifact_id"]))
                created.append(completed)

            with patch.object(job_registry, "get", return_value=None):
                restored = compilation_service.get_compilation(
                    created[0]["compilation_id"],
                    owner_id=self.owner_id,
                )
            self.assertEqual(restored["status"], "completed")
            self.assertEqual(restored["output_artifact_id"], created[0]["output_artifact_id"])
            self.assertNotEqual(created[0]["compilation_id"], created[1]["compilation_id"])
            self.assertNotEqual(created[0]["output_artifact_id"], created[1]["output_artifact_id"])
            self.assertNotEqual(fake_storage.uploaded[0][0], fake_storage.uploaded[1][0])
            self.assertTrue(all(key.startswith("projects/compile-project/renders/") for key, _, _ in fake_storage.uploaded))
            metadata = project_service.load_project_metadata("compile-project")
            compilation_artifacts = [item for item in metadata["artifacts"] if item["kind"] == "compilation"]
            self.assertEqual(len(compilation_artifacts), 2)
            self.assertTrue(all(item["status"] == "completed" for item in compilation_artifacts))
            library = self.client.get("/api/library")
            self.assertEqual(library.status_code, 200)
            self.assertEqual(
                {item["artifact_id"] for item in library.json()["items"] if item["kind"] == "compilation"},
                {item["output_artifact_id"] for item in created},
            )
            self.assertFalse((self.root / "processing" / "temp" / "compilations" / created[0]["compilation_id"]).exists())
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    def test_compilation_running_status_reports_job_progress(self) -> None:
        from threading import Event

        entered_render = Event()
        continue_render = Event()

        class FakeStorage:
            def exists(self, _key):
                return False

            def upload_file(self, _source, _key, content_type=None):
                return None

        project_dir = self._create_project("compile-progress")
        (project_dir / "source.mp4").write_bytes(b"source")
        patchers = self._compilation_test_patches(FakeStorage())

        def blocking_render(_source, _start, _end, _config, _ass, output, progress_callback=None):
            if progress_callback:
                progress_callback({"out_time_us": "5000000"})
            entered_render.set()
            if not continue_render.wait(timeout=5):
                raise RuntimeError("Test render gate timed out.")
            output.write_bytes(b"normalized segment")

        patchers[3] = patch.object(compilation_service, "render_short", side_effect=blocking_render)
        for patcher in patchers:
            patcher.start()
        response = None
        compilation_id = None
        try:
            response = self.client.post(
                "/api/projects/compile-progress/compilations",
                json={
                    "segments": [{"candidate_id": 1}],
                    "max_total_duration_seconds": 30,
                    "render_settings": {"captions_enabled": False},
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            compilation_id = response.json()["compilation_id"]
            self.assertTrue(entered_render.wait(timeout=3))
            running = self.client.get(f"/api/compilations/{compilation_id}").json()
            self.assertEqual(running["status"], "running")
            self.assertGreater(running["progress"], 0.0)
            self.assertLessEqual(running["progress"], 85.0)
        finally:
            continue_render.set()
            if response is not None and response.status_code == 200 and compilation_id is not None:
                self._wait_for_compilation(compilation_id)
            for patcher in reversed(patchers):
                patcher.stop()

    def test_ffmpeg_concat_failure_fails_job_and_cleans_segment_files(self) -> None:
        class FakeStorage:
            def __init__(self):
                self.uploaded = []

            def exists(self, _key):
                return False

            def upload_file(self, source, key, content_type=None):
                self.uploaded.append(key)

        project_dir = self._create_project("compile-ffmpeg-fail")
        (project_dir / "source.mp4").write_bytes(b"source")
        fake_storage = FakeStorage()
        patchers = self._compilation_test_patches(fake_storage)
        patchers[4] = patch.object(
            compilation_service,
            "run_subprocess",
            side_effect=RuntimeError("FFmpeg concat failed"),
        )
        for patcher in patchers:
            patcher.start()
        try:
            response = self.client.post(
                "/api/projects/compile-ffmpeg-fail/compilations",
                json={
                    "segments": [{"candidate_id": 1}],
                    "max_total_duration_seconds": 30,
                    "render_settings": {"captions_enabled": False},
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            failed = self._wait_for_compilation(response.json()["compilation_id"])
            self.assertEqual(failed["status"], "failed")
            self.assertIn("FFmpeg concat failed", failed["failure"])
            self.assertEqual(fake_storage.uploaded, [])
            self.assertFalse(
                (self.root / "processing" / "temp" / "compilations" / failed["compilation_id"]).exists()
            )
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    def test_compilation_upload_failure_is_failed_and_cleans_temporary_output(self) -> None:
        class FailingStorage:
            def exists(self, _key):
                return False

            def upload_file(self, _source, _key, content_type=None):
                raise StorageError("upload failed")

        project_dir = self._create_project("compile-upload-fail")
        (project_dir / "source.mp4").write_bytes(b"source")
        patchers = self._compilation_test_patches(FailingStorage())
        for patcher in patchers:
            patcher.start()
        try:
            response = self.client.post(
                "/api/projects/compile-upload-fail/compilations",
                json={
                    "segments": [{"candidate_id": 1}],
                    "max_total_duration_seconds": 30,
                    "render_settings": {"captions_enabled": False},
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            failed = self._wait_for_compilation(response.json()["compilation_id"])
            self.assertEqual(failed["status"], "failed")
            self.assertIn("upload failed", failed["failure"])
            self.assertIsNone(failed["output_artifact_id"])
            failed_job = job_registry.get(failed["parent_job_id"])
            output = self.output_root / f"compilation_{failed_job.artifact_id}.mp4"
            self.assertFalse(output.exists())
            metadata = project_service.load_project_metadata("compile-upload-fail")
            self.assertFalse(any(item.get("kind") == "compilation" for item in metadata.get("artifacts", [])))
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    def test_compilation_status_and_creation_are_owner_scoped(self) -> None:
        other_client = self._authenticated_client("compilation-other@example.com", "other-password-123")
        other_id = other_client.get("/api/auth/me").json()["user"]["id"]
        self._create_project("compilation-owner", owner_id=self.owner_id)
        self._create_project("compilation-other", owner_id=other_id)
        parent = job_registry.create("compilation", video_id="compilation-owner")
        project_service.save_compilation_record(
            "compilation-owner",
            {
                "compilation_id": "compilation-private-id",
                "project_id": "compilation-owner",
                "owner_id": self.owner_id,
                "parent_job_id": parent.id,
                "status": "queued",
                "progress": 0.0,
                "segments": [{"candidate_id": 1, "start": 12.0, "end": 24.0, "duration": 12.0}],
                "effective_duration_seconds": 12.0,
                "created_at": parent.created_at,
            },
        )
        self.assertEqual(self.client.get("/api/compilations/compilation-private-id").status_code, 200)
        self.assertEqual(other_client.get("/api/compilations/compilation-private-id").status_code, 404)
        self.assertEqual(
            other_client.post(
                "/api/projects/compilation-owner/compilations",
                json={"segments": [{"candidate_id": 1}], "max_total_duration_seconds": 30},
            ).status_code,
            404,
        )

    def test_render_queue_missing_job_returns_404(self) -> None:
        response = self.client.get("/api/renders/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_render_jobs_are_scoped_to_verified_project_owners(self) -> None:
        other_client = self._authenticated_client("other@example.com", "other-password-123")
        other_id = other_client.get("/api/auth/me").json()["user"]["id"]
        self._create_project("owner-project", owner_id=self.owner_id)
        self._create_project("other-project", owner_id=other_id)
        self._create_project("unowned-project", owner_id="")

        owner_job = job_registry.create("render", video_id="owner-project")
        other_job = job_registry.create("render", video_id="other-project")
        unowned_job = job_registry.create("render", video_id="unowned-project")
        missing_project_job = job_registry.create("render", video_id="missing-project")
        job_registry.update(owner_job.id, status="completed")

        owner_jobs = self.client.get("/api/renders")
        self.assertEqual(owner_jobs.status_code, 200)
        self.assertEqual([job["id"] for job in owner_jobs.json()], [owner_job.id])

        other_jobs = other_client.get("/api/renders")
        self.assertEqual(other_jobs.status_code, 200)
        self.assertEqual([job["id"] for job in other_jobs.json()], [other_job.id])

        self.assertEqual(self.client.get(f"/api/renders/{owner_job.id}").status_code, 200)
        self.assertEqual(other_client.get(f"/api/renders/{owner_job.id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/renders/{unowned_job.id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/renders/{missing_project_job.id}").status_code, 404)

        project_renders = self.client.get("/api/projects/owner-project/renders")
        self.assertEqual(project_renders.status_code, 200)
        self.assertEqual([job["id"] for job in project_renders.json()], [owner_job.id])
        self.assertEqual(other_client.get("/api/projects/owner-project/renders").status_code, 404)

        self.assertEqual(self.client.delete(f"/api/renders/{owner_job.id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/renders/{other_job.id}").status_code, 404)

    def test_render_history_restores_completed_jobs_and_marks_active_jobs_interrupted(self) -> None:
        self._create_project()
        history_dir = self.root / "processing" / "temp" / "render_jobs"
        history_dir.mkdir(parents=True, exist_ok=True)

        completed_path = history_dir / "11111111-1111-1111-1111-111111111111.json"
        running_path = history_dir / "22222222-2222-2222-2222-222222222222.json"
        malformed_path = history_dir / "broken.json"

        completed_path.write_text(
            json.dumps(
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "kind": "render",
                    "video_id": "abc123XYZ_1",
                    "candidate_id": 1,
                    "status": "completed",
                    "stage": "done",
                    "message": "Done",
                    "output_path": str(self.output_root / "render_1.mp4"),
                    "output_url": "/media/shorts/render_1.mp4",
                    "result": {"request_signature": {"start": 12.0, "end": 24.0, "render_settings": {}}},
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:01:00+00:00",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        running_path.write_text(
            json.dumps(
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "kind": "render",
                    "video_id": "abc123XYZ_1",
                    "candidate_id": 1,
                    "status": "running",
                    "stage": "encoding",
                    "message": "Working",
                    "created_at": "2026-01-01T00:02:00+00:00",
                    "updated_at": "2026-01-01T00:03:00+00:00",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        malformed_path.write_text("not-json", encoding="utf-8")

        job_registry.reset()
        job_registry.restore_from_disk()

        completed = job_registry.get("11111111-1111-1111-1111-111111111111")
        interrupted = job_registry.get("22222222-2222-2222-2222-222222222222")

        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(interrupted)
        self.assertEqual(interrupted.status, "interrupted")
        self.assertEqual(interrupted.stage, "interrupted")

    def test_remote_active_compilation_is_marked_interrupted_after_restart(self) -> None:
        job_id = "33333333-3333-3333-3333-333333333333"
        payload = {
            "id": job_id,
            "kind": "compilation",
            "video_id": "abc123XYZ_1",
            "status": "running",
            "stage": "rendering",
            "percent": 42.0,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:01:00+00:00",
        }

        class FakeR2(S3Storage):
            def __init__(self):
                self.objects = {f"jobs/{job_id}.json": json.dumps(payload).encode("utf-8")}

            def list_keys(self, prefix):
                return [key for key in self.objects if key.startswith(prefix)]

            def get_bytes(self, key):
                return self.objects[key]

            def put_bytes(self, key, data, content_type=None):
                self.objects[key] = data

        job_registry.reset()
        fake_storage = FakeR2()
        with patch("backend.services.job_registry.storage", fake_storage):
            job_registry.restore_from_disk()
        restored = job_registry.get(job_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, "interrupted")
        self.assertEqual(restored.stage, "interrupted")
        self.assertEqual(restored.message, "Interrupted by backend restart.")

    def test_retry_preserves_snapshot_and_links_prior_job(self) -> None:
        self._create_project()
        original = job_registry.create(
            "render",
            video_id="abc123XYZ_1",
            candidate_id=1,
            stage="failed",
            message="Failed",
            result={
                "request_signature": {
                    "video_id": "abc123XYZ_1",
                    "candidate_id": 1,
                    "start": 14.0,
                    "end": 26.0,
                    "render_settings": {"captions_enabled": False},
                }
            },
        )
        job_registry.update(original.id, status="failed", error="Render failed")

        def fake_render_short(source_path, start, end, config, ass_path, output_path, progress_callback=None):
            output_path.write_bytes(b"rendered")

        with patch.object(render_service, "render_short", side_effect=fake_render_short):
            retried_ids = render_service.retry_render_job(original.id)

        self.assertEqual(len(retried_ids), 1)
        self._wait_for_job_completion(retried_ids[0])

        retried = job_registry.get(retried_ids[0])
        self.assertIsNotNone(retried)
        self.assertEqual(retried.retry_of, original.id)
        self.assertEqual(retried.result["request_signature"]["start"], 14.0)

    def test_malformed_history_entries_are_ignored_during_restore(self) -> None:
        history_dir = self.root / "processing" / "temp" / "render_jobs"
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "duplicate.json").write_text("{", encoding="utf-8")

        job_registry.reset()
        job_registry.restore_from_disk()

        self.assertEqual(job_registry.list(), [])


if __name__ == "__main__":
    unittest.main()
