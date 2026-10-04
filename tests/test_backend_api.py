import json
import tempfile
import time
import unittest
from threading import Event
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
import backend.services.project_service as project_service
import backend.services.render_service as render_service
from backend.services.job_registry import job_registry
from backend.services.auth import auth_repository


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
            patch.object(render_service, "PROCESSING_TEMP_DIR", self.root / "processing" / "temp"),
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
        self.client.headers.update({"Origin": "http://localhost:5173", "X-CSRF-Token": self.client.cookies.get("clippy_csrf")})

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        job_registry.reset()
        self.tempdir.cleanup()

    def _create_project(self, video_id: str = "abc123XYZ_1") -> Path:
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
        short_path = self.output_root / "short_2026-09-27_001.mp4"
        short_path.write_bytes(b"video")

        response = self.client.get("/api/library")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["filename"], short_path.name)

        delete_response = self.client.delete(f"/api/library/{short_path.name}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(short_path.exists())

        with self.assertRaises(ValueError):
            project_service.safe_output_path("..\\evil.mp4")

    def test_render_queue_missing_job_returns_404(self) -> None:
        response = self.client.get("/api/renders/does-not-exist")
        self.assertEqual(response.status_code, 404)

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
