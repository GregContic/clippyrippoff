import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import caption_preset_service
from backend.services.job_registry import job_registry


class TestReviewAndPresets(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.output = self.root / "output" / "shorts"
        self.output.mkdir(parents=True)
        self.patches = [
            patch("backend.api.renders.OUTPUT_SHORTS_DIR", self.output),
            patch.object(job_registry, "storage_dir", self.root / "jobs"),
            patch.object(caption_preset_service, "PRESETS_PATH", self.root / "caption_presets.json"),
        ]
        for patcher in self.patches:
            patcher.start()
        job_registry.reset()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        job_registry.reset()
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tempdir.cleanup()

    def test_review_requires_completed_job_and_existing_output(self) -> None:
        job = job_registry.create("render")
        job_registry.update(job.id, status="running", output_path=str(self.output / "short.mp4"))
        response = self.client.patch(f"/api/renders/{job.id}/review", json={"status": "approved"})
        self.assertEqual(response.status_code, 400)

        job_registry.update(job.id, status="completed")
        response = self.client.patch(f"/api/renders/{job.id}/review", json={"status": "approved", "notes": "Looks good"})
        self.assertEqual(response.status_code, 400)

        (self.output / "short.mp4").write_bytes(b"video")
        response = self.client.patch(f"/api/renders/{job.id}/review", json={"status": "approved", "notes": "Looks good"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["review_status"], "approved")
        self.assertEqual(response.json()["review_notes"], "Looks good")
        self.assertEqual(job_registry.get(job.id).review_status, "approved")

    def test_caption_presets_are_validated_and_persisted(self) -> None:
        response = self.client.get("/api/caption-presets")
        self.assertEqual(response.status_code, 200)
        self.assertTrue({"clean", "bold", "gaming", "minimal", "gaming-pop", "karaoke-highlight", "smooth-fade"}.issubset({item["id"] for item in response.json()}))

        created = self.client.post("/api/caption-presets", json={
            "name": "My Style",
            "settings": {"caption_font_name": "Arial", "caption_font_size": 70, "caption_primary_color": "&H00FFFFFF"},
        })
        self.assertEqual(created.status_code, 200)
        preset_id = created.json()["id"]
        self.assertEqual(self.client.get("/api/caption-presets").status_code, 200)
        self.assertEqual(self.client.put(f"/api/caption-presets/{preset_id}", json={"name": "Renamed", "settings": {"caption_font_size": 80}}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/caption-presets/{preset_id}").status_code, 200)

        invalid = self.client.post("/api/caption-presets", json={"name": "Unsafe", "settings": {"caption_font_size": 999}})
        self.assertEqual(invalid.status_code, 422)
        unsupported = self.client.post("/api/caption-presets", json={"name": "Unsupported", "settings": {"caption_animation": "shake"}})
        self.assertEqual(unsupported.status_code, 422)


if __name__ == "__main__":
    unittest.main()
