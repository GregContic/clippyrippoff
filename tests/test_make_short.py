"""Tests for scripts/make_short.py — pure Python logic (crop math, caption
chunking/formatting). No FFmpeg or real video required."""
import unittest
import tempfile
from pathlib import Path

from tests import SCRIPTS_DIR  # noqa: F401 (ensures scripts/ is importable)
from make_short import (
    _format_ass_time,
    build_caption_cues,
    compute_center_crop,
    write_ass_subtitles,
)


class TestComputeCenterCrop(unittest.TestCase):
    def test_widescreen_source_crops_sides(self):
        # 1920x1080 (16:9) -> 1080x1920 (9:16): crop width, keep full height.
        crop = compute_center_crop(1920, 1080, 1080, 1920)
        self.assertEqual(crop.height, 1080)
        self.assertLess(crop.width, 1920)
        self.assertEqual(crop.x, (1920 - crop.width) // 2)
        self.assertEqual(crop.y, 0)
        # Cropped region must already match the target aspect ratio.
        self.assertAlmostEqual(crop.width / crop.height, 1080 / 1920, places=2)

    def test_already_vertical_source_crops_top_bottom(self):
        crop = compute_center_crop(1080, 2400, 1080, 1920)
        self.assertEqual(crop.width, 1080)
        self.assertLess(crop.height, 2400)
        self.assertEqual(crop.y, (2400 - crop.height) // 2)

    def test_never_exceeds_source_dimensions(self):
        crop = compute_center_crop(640, 360, 1080, 1920)
        self.assertLessEqual(crop.width, 640)
        self.assertLessEqual(crop.height, 360)


class TestFormatAssTime(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_format_ass_time(0), "0:00:00.00")

    def test_sub_minute(self):
        self.assertEqual(_format_ass_time(12.45), "0:00:12.45")

    def test_over_an_hour(self):
        self.assertEqual(_format_ass_time(3661.5), "1:01:01.50")

    def test_negative_clamped_to_zero(self):
        self.assertEqual(_format_ass_time(-3), "0:00:00.00")


class TestBuildCaptionCues(unittest.TestCase):
    def setUp(self):
        self.segments = [
            {"start": 5.0, "end": 8.0, "text": "NO WAY HE ACTUALLY DID THAT"},
            {"start": 20.0, "end": 22.0, "text": "outside the clip window"},
        ]

    def test_only_overlapping_segments_included(self):
        cues = build_caption_cues(
            self.segments, clip_start=0, clip_end=10,
            max_words_per_chunk=5, max_chars_per_line=18, max_lines=2,
        )
        joined = " ".join(word for cue in cues for line in cue.lines for word in line.split())
        self.assertIn("NO", joined)
        self.assertNotIn("outside", joined)

    def test_times_relative_to_clip_start(self):
        cues = build_caption_cues(
            self.segments, clip_start=2, clip_end=10,
            max_words_per_chunk=10, max_chars_per_line=100, max_lines=5,
        )
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0].start, 3.0)  # 5.0 - 2 (clip_start)
        self.assertAlmostEqual(cues[0].end, 6.0)    # 8.0 - 2

    def test_chunking_splits_long_segment(self):
        cues = build_caption_cues(
            self.segments, clip_start=0, clip_end=10,
            max_words_per_chunk=2, max_chars_per_line=100, max_lines=5,
        )
        # 6 words / 2 per chunk = 3 chunks
        self.assertEqual(len(cues), 3)
        for cue in cues:
            self.assertLessEqual(len(" ".join(cue.lines).split()), 2)

    def test_line_wrapping_respects_max_lines_and_chars(self):
        cues = build_caption_cues(
            self.segments, clip_start=0, clip_end=10,
            max_words_per_chunk=6, max_chars_per_line=10, max_lines=2,
        )
        self.assertEqual(len(cues), 1)
        self.assertLessEqual(len(cues[0].lines), 2)

    def test_no_overlap_returns_empty(self):
        cues = build_caption_cues(
            self.segments, clip_start=100, clip_end=110,
            max_words_per_chunk=5, max_chars_per_line=18, max_lines=2,
        )
        self.assertEqual(cues, [])

    def test_word_timestamps_are_preserved_and_trim_relative(self):
        cues = build_caption_cues(
            [{"start": 10.0, "end": 14.0, "text": "hello world", "words": [{"start": 10.0, "end": 11.0, "word": "hello"}, {"start": 11.0, "end": 14.0, "word": "world"}]}],
            clip_start=10.5, clip_end=14,
            max_words_per_chunk=5, max_chars_per_line=30, max_lines=2,
        )
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0].words[0].start, 0.0)
        self.assertAlmostEqual(cues[0].words[1].start, 0.5)

    def test_invalid_word_timestamps_use_segment_fallback(self):
        cues = build_caption_cues(
            [{"start": 5.0, "end": 8.0, "text": "NO WAY", "words": [{"start": 7.0, "end": 6.0, "word": "NO"}]}],
            clip_start=0, clip_end=10,
            max_words_per_chunk=5, max_chars_per_line=30, max_lines=2,
        )
        self.assertEqual(cues[0].words, [])


class TestAnimatedAssSubtitles(unittest.TestCase):
    def test_supported_animations_write_ass_events(self):
        from make_short import build_caption_cues
        segments = [{"start": 5.0, "end": 7.0, "text": "hello world", "words": [{"start": 5.0, "end": 6.0, "word": "hello"}, {"start": 6.0, "end": 7.0, "word": "world"}]}]
        cues = build_caption_cues(segments, 5.0, 7.0, 5, 30, 2)
        with tempfile.TemporaryDirectory() as directory:
            for animation, marker in (("none", "hello world"), ("fade", r"\fad"), ("pop", r"\fscx80"), ("karaoke", r"\k")):
                path = Path(directory) / f"{animation}.ass"
                write_ass_subtitles(cues, {"output_width": 1080, "output_height": 1920, "caption_animation": animation}, path)
                text = path.read_text(encoding="utf-8")
                self.assertIn(marker, text)
                self.assertNotIn(r"\n", text)

    def test_pop_fallback_keeps_ass_line_breaks(self):
        from make_short import CaptionCue

        cue = CaptionCue(start=0.0, end=1.0, lines=["first line", "second line"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pop.ass"
            write_ass_subtitles([cue], {"output_width": 1080, "output_height": 1920, "caption_animation": "pop"}, path)
            text = path.read_text(encoding="utf-8")
            self.assertIn(r"\N", text)
            self.assertNotIn(r"\\N", text)


if __name__ == "__main__":
    unittest.main()
