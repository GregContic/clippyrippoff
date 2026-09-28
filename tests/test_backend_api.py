import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
import backend.services.project_service as project_service
import backend.services.render_service as render_service


class TestBackendApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.cache_root = self.root / "processing" / "temp" / "youtube"
        self.output_root = self.root / "output" / "shorts"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)

        self.patches = [
            patch.object(project_service, "PROJECT_CACHE_DIR", self.cache_root),
            patch.object(project_service, "OUTPUT_SHORTS_DIR", self.output_root),
            patch.object(project_service, "PROCESSING_TEMP_DIR", self.root / "processing" / "temp"),
            patch.object(render_service, "OUTPUT_SHORTS_DIR", self.output_root),
            patch.object(render_service, "PROCESSING_TEMP_DIR", self.root / "processing" / "temp"),
            patch.object(project_service, "get_media_info", return_value={"duration": 12.0}),
        ]
        for patcher in self.patches:
            patcher.start()

        self.client = TestClient(app)

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
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
        (project_dir / "source.mp4").write_bytes(b"fake-video")
        return project_dir

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


if __name__ == "__main__":
    unittest.main()
