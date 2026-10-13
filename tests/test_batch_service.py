import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.services.batch_service import select_batch_candidates
from backend.services.job_registry import job_registry


class TestBatchSelection(unittest.TestCase):
    def test_selection_prefers_score_and_suppresses_overlap_and_spacing(self) -> None:
        candidates = [
            {"id": 1, "start": 10, "end": 70, "candidate_score": 90, "trigger_time": 40},
            {"id": 2, "start": 42, "end": 80, "candidate_score": 99, "trigger_time": 55},
            {"id": 3, "start": 120, "end": 135, "candidate_score": 80, "trigger_time": 127},
        ]
        with patch("backend.services.batch_service.load_candidates", return_value={"candidates": candidates}), patch(
            "backend.services.batch_service.load_config",
            return_value={"clip_min_seconds": 10, "clip_max_seconds": 60, "max_candidates": 10},
        ):
            selected = select_batch_candidates(
                "video-id",
                target_duration_seconds=30,
                minimum_spacing_seconds=20,
                max_clips=None,
                candidate_ids=None,
            )
        self.assertEqual([item["candidate_id"] for item in selected], [2, 3])
        self.assertTrue(all(item["end"] - item["start"] <= 30 for item in selected))

    def test_invalid_requested_candidates_create_no_selection(self) -> None:
        with patch("backend.services.batch_service.load_candidates", return_value={"candidates": [{"id": 1, "start": 0, "end": 5}]}), patch(
            "backend.services.batch_service.load_config",
            return_value={"clip_min_seconds": 10, "clip_max_seconds": 60, "max_candidates": 10},
        ):
            with self.assertRaisesRegex(ValueError, "cannot produce"):
                select_batch_candidates(
                    "video-id",
                    target_duration_seconds=30,
                    minimum_spacing_seconds=0,
                    max_clips=None,
                    candidate_ids=[1],
                )

    def test_parent_reports_partial_failure_without_hiding_successful_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(job_registry, "storage_dir", Path(directory)):
                job_registry.reset()
                parent = job_registry.create("batch", result={"child_job_ids": []})
                successful = job_registry.create("render", artifact_id="artifact-a")
                failed = job_registry.create("render", artifact_id="artifact-b")
                job_registry.update(successful.id, status="completed", percent=100.0)
                job_registry.update(failed.id, status="failed", error="FFmpeg failed", percent=0.0)
                updated = job_registry.update_parent_from_children(parent.id, [successful.id, failed.id])
                self.assertIsNotNone(updated)
                self.assertEqual(updated.status, "partially_completed")
                self.assertEqual(updated.percent, 50.0)
                self.assertEqual(job_registry.get(successful.id).status, "completed")
            job_registry.reset()
