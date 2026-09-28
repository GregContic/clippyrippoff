"""Tests for scripts/utils.py — pure Python logic, no FFmpeg or Whisper required."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import SCRIPTS_DIR  # noqa: F401 (ensures scripts/ is importable)
from utils import (
    ValidationError,
    generate_output_filename,
    load_config,
    load_transcript,
    parse_timestamp,
    validate_clip_range,
)


class TestParseTimestamp(unittest.TestCase):
    def test_plain_seconds(self):
        self.assertEqual(parse_timestamp("32"), 32.0)
        self.assertEqual(parse_timestamp(32), 32.0)
        self.assertEqual(parse_timestamp(32.5), 32.5)

    def test_mm_ss(self):
        self.assertEqual(parse_timestamp("1:12"), 72.0)

    def test_hh_mm_ss(self):
        self.assertEqual(parse_timestamp("0:01:12"), 72.0)

    def test_negative_rejected(self):
        with self.assertRaises(ValidationError):
            parse_timestamp("-5")

    def test_garbage_rejected(self):
        with self.assertRaises(ValidationError):
            parse_timestamp("not-a-time")

    def test_bad_colon_format_rejected(self):
        with self.assertRaises(ValidationError):
            parse_timestamp("1:2:3:4")


class TestValidateClipRange(unittest.TestCase):
    def test_valid_range(self):
        validate_clip_range(10, 30, min_seconds=10, max_seconds=60)  # should not raise

    def test_negative_start(self):
        with self.assertRaises(ValidationError):
            validate_clip_range(-1, 10, min_seconds=10, max_seconds=60)

    def test_end_before_start(self):
        with self.assertRaises(ValidationError):
            validate_clip_range(30, 10, min_seconds=10, max_seconds=60)

    def test_end_equals_start(self):
        with self.assertRaises(ValidationError):
            validate_clip_range(30, 30, min_seconds=10, max_seconds=60)

    def test_too_short(self):
        with self.assertRaises(ValidationError):
            validate_clip_range(10, 15, min_seconds=10, max_seconds=60)

    def test_too_long(self):
        with self.assertRaises(ValidationError):
            validate_clip_range(0, 120, min_seconds=10, max_seconds=60)

    def test_exceeds_source_duration(self):
        with self.assertRaises(ValidationError):
            validate_clip_range(0, 30, min_seconds=10, max_seconds=60, video_duration=20)


class TestGenerateOutputFilename(unittest.TestCase):
    def test_avoids_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            first = generate_output_filename(out_dir, prefix="short")
            first.write_bytes(b"x")
            second = generate_output_filename(out_dir, prefix="short")
            self.assertNotEqual(first, second)
            self.assertTrue(second.name.endswith("_002.mp4"))

    def test_predictable_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            path = generate_output_filename(out_dir, prefix="short")
            self.assertRegex(path.name, r"^short_\d{4}-\d{2}-\d{2}_\d{3}\.mp4$")


class TestLoadConfig(unittest.TestCase):
    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"output_width": 1080}), encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config["output_width"], 1080)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_config(path)

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)


class TestLoadTranscript(unittest.TestCase):
    def test_valid_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            data = {"source": "gameplay.mp4", "segments": [{"start": 1.0, "end": 2.0, "text": "hi"}]}
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_transcript(path)
            self.assertEqual(loaded["segments"][0]["text"], "hi")

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_transcript(Path("does_not_exist.json"))

    def test_malformed_missing_segments_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            path.write_text(json.dumps({"source": "x.mp4"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_transcript(path)

    def test_malformed_segment_missing_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            data = {"source": "x.mp4", "segments": [{"start": 1.0, "text": "hi"}]}
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_transcript(path)


if __name__ == "__main__":
    unittest.main()
