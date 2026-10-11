"""Offline tests for YouTube URL validation, caching, and metadata."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import SCRIPTS_DIR  # noqa: F401
from detect_clips import main as detect_main
from youtube import (
    BOT_CHALLENGE_MESSAGE,
    InvalidYouTubeURLError,
    YouTubeBotChallengeError,
    YouTubeError,
    download_youtube_video,
    extract_video_id,
)


class FakeYoutubeDL:
    calls = 0
    last_options = None

    def __init__(self, options):
        self.options = options
        FakeYoutubeDL.last_options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def extract_info(self, url, download=True):
        FakeYoutubeDL.calls += 1
        output_template = self.options["outtmpl"]
        output_path = Path(output_template.replace("%(ext)s", "mp4"))
        output_path.write_bytes(b"fake-video")
        return {"id": "abc123XYZ_1", "title": "Authorized Test Video"}


class TestYouTubeUrlParsing(unittest.TestCase):
    def test_watch_url(self):
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=abc123XYZ_1"), "abc123XYZ_1")

    def test_short_url(self):
        self.assertEqual(extract_video_id("https://youtu.be/abc123XYZ_1"), "abc123XYZ_1")

    def test_shorts_url(self):
        self.assertEqual(extract_video_id("https://youtube.com/shorts/abc123XYZ_1"), "abc123XYZ_1")

    def test_invalid_url(self):
        with self.assertRaises(InvalidYouTubeURLError):
            extract_video_id("https://example.com/watch?v=abc123XYZ_1")

    def test_missing_video_id(self):
        with self.assertRaises(InvalidYouTubeURLError):
            extract_video_id("https://www.youtube.com/watch")


class TestYouTubeCache(unittest.TestCase):
    def test_download_returns_metadata_and_reuses_valid_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            FakeYoutubeDL.calls = 0
            with patch("youtube._load_yt_dlp", return_value=type("Module", (), {"YoutubeDL": FakeYoutubeDL})):
                first = download_youtube_video(
                    "https://youtu.be/abc123XYZ_1", output_dir=cache_root
                )
                second = download_youtube_video(
                    "https://youtu.be/abc123XYZ_1", output_dir=cache_root
                )
            self.assertEqual(FakeYoutubeDL.calls, 1)
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(second["video_id"], "abc123XYZ_1")
            self.assertEqual(second["title"], "Authorized Test Video")
            self.assertTrue(Path(second["filepath"]).exists())
            self.assertEqual(FakeYoutubeDL.last_options["js_runtimes"], {"node": {}})

    def test_bot_challenge_returns_safe_user_message_and_redacts_diagnostics(self):
        class BotChallengeYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=True):
                self.options["logger"].error(
                    "Extraction failed for "
                    "https://youtube.com/watch?v=abc123XYZ_1&token=private-value"
                )
                raise RuntimeError(
                    "Sign in to confirm you’re not a bot: "
                    "https://youtube.com/watch?v=abc123XYZ_1&token=private-value"
                )

        with tempfile.TemporaryDirectory() as directory:
            with patch("youtube._load_yt_dlp", return_value=type("Module", (), {"YoutubeDL": BotChallengeYoutubeDL})):
                with self.assertLogs("youtube", level="WARNING") as logs:
                    with self.assertRaises(YouTubeBotChallengeError) as raised:
                        download_youtube_video(
                            "https://youtu.be/abc123XYZ_1", output_dir=Path(directory)
                        )

        self.assertEqual(str(raised.exception), BOT_CHALLENGE_MESSAGE)
        self.assertNotIn("private-value", "\n".join(logs.output))
        self.assertIn("[REDACTED]", "\n".join(logs.output))

    def test_other_extraction_errors_do_not_expose_raw_details(self):
        class FailingYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=True):
                raise RuntimeError("private extraction details")

        with tempfile.TemporaryDirectory() as directory:
            with patch("youtube._load_yt_dlp", return_value=type("Module", (), {"YoutubeDL": FailingYoutubeDL})):
                with self.assertRaises(YouTubeError) as raised:
                    download_youtube_video(
                        "https://youtu.be/abc123XYZ_1", output_dir=Path(directory)
                    )

        self.assertNotIn("private extraction details", str(raised.exception))

    def test_force_download_ignores_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            FakeYoutubeDL.calls = 0
            with patch("youtube._load_yt_dlp", return_value=type("Module", (), {"YoutubeDL": FakeYoutubeDL})):
                download_youtube_video("https://youtu.be/abc123XYZ_1", output_dir=cache_root)
                download_youtube_video(
                    "https://youtu.be/abc123XYZ_1", output_dir=cache_root, force_download=True
                )
            self.assertEqual(FakeYoutubeDL.calls, 2)

    def test_metadata_file_is_stable_json(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            with patch("youtube._load_yt_dlp", return_value=type("Module", (), {"YoutubeDL": FakeYoutubeDL})):
                download_youtube_video("https://youtu.be/abc123XYZ_1", output_dir=cache_root)
            metadata = json.loads((cache_root / "abc123XYZ_1" / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["video_id"], "abc123XYZ_1")


class TestSourceValidation(unittest.TestCase):
    def test_neither_source_is_rejected(self):
        self.assertEqual(detect_main([]), 2)

    def test_both_sources_are_rejected(self):
        self.assertEqual(
            detect_main(["--video", "local.mp4", "--url", "https://youtu.be/abc123XYZ_1"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
