"""Offline tests for YouTube URL validation, caching, and metadata."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import SCRIPTS_DIR  # noqa: F401
from detect_clips import main as detect_main
import youtube
from youtube import (
    BOT_CHALLENGE_MESSAGE,
    InvalidYouTubeURLError,
    YouTubeBotChallengeError,
    YouTubeError,
    _classify_extraction_error,
    _safe_diagnostic,
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
    def setUp(self):
        youtube._DOWNLOAD_LOCKS.clear()
        youtube._EXTRACTION_COOLDOWNS.clear()

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
            self.assertEqual(
                FakeYoutubeDL.last_options["socket_timeout"],
                youtube.YOUTUBE_SOCKET_TIMEOUT_SECONDS,
            )
            self.assertEqual(FakeYoutubeDL.last_options["retries"], 0)
            self.assertEqual(FakeYoutubeDL.last_options["fragment_retries"], 0)
            self.assertEqual(FakeYoutubeDL.last_options["extractor_retries"], 0)

    def test_duplicate_download_request_is_rejected_while_in_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = download_youtube_video.__globals__["_lock_for_video"]("abc123XYZ_1")
            acquired = lock.acquire(blocking=False)
            self.assertTrue(acquired)
            try:
                with patch("youtube._load_yt_dlp", return_value=type("Module", (), {"YoutubeDL": FakeYoutubeDL})):
                    with self.assertRaises(YouTubeError):
                        download_youtube_video("https://youtu.be/abc123XYZ_1", output_dir=Path(directory))
            finally:
                lock.release()

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
        self.assertEqual(
            raised.exception.retry_after_seconds,
            youtube.BOT_CHALLENGE_COOLDOWN_SECONDS,
        )

    def test_missing_visitor_data_is_a_terminal_bot_challenge(self):
        error = _classify_extraction_error(
            RuntimeError("Unable to fetch GVS PO Token: Missing required Visitor Data")
        )
        self.assertIsInstance(error, YouTubeBotChallengeError)
        self.assertEqual(str(error), BOT_CHALLENGE_MESSAGE)

    def test_visitor_data_and_po_tokens_are_redacted(self):
        diagnostic = _safe_diagnostic(
            "visitor_data=private-visitor po_token:private-token authorization=Bearer private-auth"
        )
        self.assertNotIn("private-visitor", diagnostic)
        self.assertNotIn("private-token", diagnostic)
        self.assertNotIn("private-auth", diagnostic)
        self.assertEqual(diagnostic.count("[REDACTED]"), 3)

    def test_spaced_visitor_data_and_po_tokens_are_redacted(self):
        diagnostic = _safe_diagnostic(
            "Visitor Data: private-visitor PO Token=private-token"
        )
        self.assertNotIn("private-visitor", diagnostic)
        self.assertNotIn("private-token", diagnostic)
        self.assertEqual(diagnostic.count("[REDACTED]"), 2)

    def test_valid_cache_remains_usable_during_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            video_dir = cache_root / "abc123XYZ_1"
            video_dir.mkdir()
            source = video_dir / "source.mp4"
            source.write_bytes(b"cached-video")
            youtube._EXTRACTION_COOLDOWNS["abc123XYZ_1"] = (
                youtube.time.monotonic() + 300,
                YouTubeBotChallengeError.failure_code,
            )

            result = download_youtube_video(
                "https://youtu.be/abc123XYZ_1",
                output_dir=cache_root,
            )

        self.assertTrue(result["cached"])
        self.assertEqual(result["filepath"], str(source))

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
