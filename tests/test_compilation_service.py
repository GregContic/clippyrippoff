import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import compilation_service
from scripts.make_short import build_caption_cues, write_ass_subtitles


class TestCompilationSegments(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            {"id": 1, "start": 10.0, "end": 22.0},
            {"id": 2, "start": 30.0, "end": 42.0},
            {"id": 3, "start": 60.0, "end": 75.0},
        ]
        self.patches = [
            patch.object(compilation_service, "load_candidates", return_value={"candidates": self.candidates}),
            patch.object(compilation_service, "get_candidate_editor_state", return_value={}),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()

    def resolve(self, segments, maximum=600, source_duration=90):
        return compilation_service.resolve_segments(
            "project-1",
            segments,
            max_total_duration_seconds=maximum,
            source_duration_seconds=source_duration,
            min_segment_seconds=10,
            max_segment_seconds=60,
        )

    def test_preserves_submitted_order_and_trim_bounds(self) -> None:
        resolved, duration = self.resolve([
            {"candidate_id": 2},
            {"candidate_id": 1, "start": 11.0, "end": 22.0},
        ])
        self.assertEqual([item["candidate_id"] for item in resolved], [2, 1])
        self.assertEqual((resolved[1]["start"], resolved[1]["end"]), (11.0, 22.0))
        self.assertEqual(duration, 23.0)

    def test_rejects_empty_duplicate_unknown_and_out_of_candidate_trims(self) -> None:
        for segments, message in (
            ([], "at least one"),
            ([{"candidate_id": 1}, {"candidate_id": 1}], "Duplicate"),
            ([{"candidate_id": 99}], "not found"),
            ([{"candidate_id": 1, "start": 9.0, "end": 21.0}], "candidate and source bounds"),
        ):
            with self.subTest(segments=segments), self.assertRaisesRegex(ValueError, message):
                self.resolve(segments)

    def test_applies_preferred_duration_by_trimming_only_final_segment(self) -> None:
        segments, duration = self.resolve(
            [{"candidate_id": 1}, {"candidate_id": 2}],
            maximum=23,
        )
        self.assertEqual([segment["candidate_id"] for segment in segments], [1, 2])
        self.assertEqual(segments[1]["start"], 30.0)
        self.assertAlmostEqual(segments[1]["end"], 41.0)
        self.assertAlmostEqual(duration, 23.0)

    def test_rejects_duration_limit_that_would_make_final_segment_too_short(self) -> None:
        with self.assertRaisesRegex(ValueError, "final moment too short"):
            self.resolve([{"candidate_id": 1}, {"candidate_id": 2}], maximum=21)

    def test_validates_source_duration_and_renderer_minimum(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the source"):
            self.resolve([{"candidate_id": 3}], source_duration=74)
        with self.assertRaisesRegex(ValueError, "at least 10"):
            self.resolve([{"candidate_id": 1, "start": 10.0, "end": 19.9}])


class TestCompilationRenderingHelpers(unittest.TestCase):
    def test_concat_command_uses_ordered_filter_inputs_and_common_audio_format(self) -> None:
        command = compilation_service.build_concat_command(
            [Path("first segment.mp4"), Path("second.mp4")],
            Path("output.mp4"),
            {"fps": 30, "output_width": 1080, "output_height": 1920},
            has_audio=True,
        )
        self.assertEqual(command[0:2], ["ffmpeg", "-y"])
        self.assertEqual(command[2:6], ["-i", "first segment.mp4", "-i", "second.mp4"])
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]", filter_graph)
        self.assertEqual(command[-1], "output.mp4")
        self.assertIn("aresample=48000", filter_graph)

    def test_concat_command_supports_sources_without_audio(self) -> None:
        command = compilation_service.build_concat_command(
            [Path("first.mp4")],
            Path("output.mp4"),
            {"fps": 30},
            has_audio=False,
        )
        self.assertIn("concat=n=1:v=1:a=0[v]", command[command.index("-filter_complex") + 1])
        self.assertIn("-an", command)

    def test_caption_cues_are_rebased_to_each_trimmed_segment(self) -> None:
        transcript = [
            {"start": 11.0, "end": 13.0, "text": "first moment caption"},
            {"start": 31.0, "end": 33.0, "text": "second moment caption"},
        ]
        first = build_caption_cues(transcript, 10.0, 14.0, 5, 18, 2)
        second = build_caption_cues(transcript, 30.0, 34.0, 5, 18, 2)
        self.assertTrue(first and second)
        self.assertAlmostEqual(first[0].start, 1.0)
        self.assertAlmostEqual(second[0].start, 1.0)

        with tempfile.TemporaryDirectory() as directory:
            ass_path = Path(directory) / "rebased.ass"
            write_ass_subtitles(second, {"output_width": 1080, "output_height": 1920}, ass_path)
            subtitle_events = [line for line in ass_path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")]
        self.assertTrue(subtitle_events)
        self.assertTrue(all("0:00:01." in line for line in subtitle_events))

    def test_output_verification_checks_existence_and_plausible_duration(self) -> None:
        config = {"output_width": 1080, "output_height": 1920}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "finished.mp4"
            output.write_bytes(b"not-empty")
            with patch.object(
                compilation_service,
                "get_media_info",
                return_value={"has_video": True, "width": 1080, "height": 1920, "duration": 20.7},
            ):
                compilation_service.verify_compilation_output(output, config, 20.0)
            with patch.object(
                compilation_service,
                "get_media_info",
                return_value={"has_video": True, "width": 1080, "height": 1920, "duration": 24.0},
            ):
                with self.assertRaisesRegex(RuntimeError, "duration"):
                    compilation_service.verify_compilation_output(output, config, 20.0)
            output.unlink()
            with self.assertRaisesRegex(RuntimeError, "missing or empty"):
                compilation_service.verify_compilation_output(output, config, 20.0)


if __name__ == "__main__":
    unittest.main()
