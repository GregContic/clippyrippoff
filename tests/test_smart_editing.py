from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.schemas import EditingSettings, RenderRequest
import backend.services.compilation_service as compilation_service
import backend.services.music_asset_service as music_asset_service
from backend.services.smart_editing import (
    apply_smart_effects,
    build_audio_filter_description,
    build_effect_command,
    validate_editing_timing,
)
from scripts.make_short import build_caption_cues, write_hook_ass


class TestEditingSettings(unittest.TestCase):
    def test_existing_render_request_without_effects_is_compatible(self):
        request = RenderRequest(candidate_ids=[1])
        self.assertIsNone(request.editing)

    def test_schema_version_and_bounds_are_validated(self):
        with self.assertRaises(ValueError):
            EditingSettings.model_validate({"schema_version": 2})
        with self.assertRaises(ValueError):
            EditingSettings(zoom_intervals=[{"start_seconds": 2, "end_seconds": 4}, {"start_seconds": 3, "end_seconds": 5}])
        with self.assertRaises(ValueError):
            EditingSettings(hook={"text": "x" * 121})
        with self.assertRaises(ValueError):
            EditingSettings(hook={"text": "safe", "color": "red"})
        with self.assertRaises(ValueError):
            EditingSettings(music={"asset_id": "music-invalid"})

    def test_hook_and_zoom_timing_must_fit_clip(self):
        settings = EditingSettings(
            hook={"text": "Opening", "start_seconds": 1, "duration_seconds": 2},
            zoom_intervals=[{"start_seconds": 4, "end_seconds": 6, "scale": 1.2}],
        )
        validate_editing_timing(settings, 7)
        with self.assertRaisesRegex(ValueError, "hook"):
            validate_editing_timing(settings, 2.5)
        with self.assertRaisesRegex(ValueError, "zoom"):
            validate_editing_timing(settings, 5)


class TestSmartEditingCommand(unittest.TestCase):
    def setUp(self):
        self.config = {
            "output_width": 1080,
            "output_height": 1920,
            "fps": 30,
            "video_codec": "libx264",
            "video_preset": "medium",
            "video_crf": 20,
            "audio_codec": "aac",
            "audio_bitrate": "192k",
        }

    def test_hook_text_is_read_from_file_and_zoom_keeps_dimensions_constant(self):
        settings = EditingSettings(
            hook={"text": "50%: safe, text", "position": "top", "background_box": True, "start_seconds": 20},
            zoom_intervals=[{"start_seconds": 1, "end_seconds": 3, "scale": 1.2}],
        )
        command = build_effect_command(
            Path("input.mp4"),
            Path("output.mp4"),
            settings=settings,
            duration_seconds=10,
            config=self.config,
            has_original_audio=True,
            hook_ass_path=Path("hook text.ass"),
        )
        joined = " ".join(command)
        self.assertIn("zoompan=", joined)
        self.assertIn("s=1080x1920", joined)
        self.assertIn("subtitles=", joined)
        self.assertNotIn("50%: safe, text", joined)
        self.assertIn("0:a?", joined)

    def test_hook_ass_escapes_text_and_uses_final_output_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hook.ass"
            write_hook_ass(
                text="50% {safe}, text\\",
                start=20,
                end=22.5,
                position="top",
                font_size=64,
                color="#FFFFFF",
                outline_width=3,
                background_box=True,
                background_color="#101010",
                config=self.config,
                ass_path=path,
            )
            content = path.read_text(encoding="utf-8")
            self.assertIn("Dialogue: 0,0:00:20.00,0:00:22.50,Hook", content)
            self.assertIn(r"50% \{safe\}, text\\", content)
            self.assertIn(",3,3,0,8,60,60,230,1", content)

    def test_segment_caption_timing_is_rebased_before_final_timeline_join(self):
        transcript = [
            {"start": 10, "end": 12, "text": "First moment"},
            {"start": 30, "end": 33, "text": "Second moment"},
        ]
        first = build_caption_cues(transcript, clip_start=10, clip_end=12, max_words_per_chunk=5, max_chars_per_line=30, max_lines=2)
        second = build_caption_cues(transcript, clip_start=30, clip_end=33, max_words_per_chunk=5, max_chars_per_line=30, max_lines=2)
        self.assertEqual((first[0].start, first[0].end), (0, 2))
        self.assertEqual((second[0].start, second[0].end), (0, 3))

    def test_music_filter_supports_looping_fades_and_activity_ducking(self):
        settings = EditingSettings(
            music={
                "asset_id": "music-" + "a" * 32,
                "volume": 0.25,
                "fade_in_seconds": 1,
                "fade_out_seconds": 2,
                "duck_original_audio": True,
            }
        )
        command = build_effect_command(
            Path("input.mp4"),
            Path("output.mp4"),
            settings=settings,
            duration_seconds=12,
            config=self.config,
            has_original_audio=True,
            music_path=Path("owned-track.mp3"),
        )
        joined = " ".join(command)
        self.assertIn("-stream_loop -1", joined)
        self.assertIn("afade=t=in", joined)
        self.assertIn("afade=t=out", joined)
        self.assertIn("sidechaincompress", joined)
        self.assertIn("alimiter=limit=0.95", joined)
        self.assertIn("volume=0.2500", joined)
        self.assertIn("amix=inputs=2", joined)

    def test_music_without_original_audio_creates_an_audio_track(self):
        settings = EditingSettings(music={"asset_id": "music-" + "b" * 32, "loop": False})
        command = build_effect_command(
            Path("input.mp4"),
            Path("output.mp4"),
            settings=settings,
            duration_seconds=8,
            config=self.config,
            has_original_audio=False,
            music_path=Path("owned-track.wav"),
        )
        joined = " ".join(command)
        self.assertNotIn("-stream_loop", joined)
        self.assertIn("[music]alimiter=limit=0.95[a]", joined)
        self.assertIn("-map [a]", joined)
        self.assertIn("-c:v copy", joined)

    def test_audio_filter_description_rebases_fades_and_ducking(self):
        settings = EditingSettings(music={
            "asset_id": "music-" + "c" * 32,
            "volume": 0.3,
            "fade_in_seconds": 1,
            "fade_out_seconds": 2,
            "duck_original_audio": True,
        })
        filters = build_audio_filter_description(settings, 12, has_original_audio=True)
        self.assertIn("afade=t=in:st=0:d=1.000", filters)
        self.assertIn("afade=t=out:st=10.000:d=2.000", filters)
        self.assertIn("sidechaincompress", filters)
        self.assertIn("volume=0.3000", filters)

    def test_apply_effects_replaces_output_and_cleans_temporary_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "clip.mp4"
            output.write_bytes(b"old")
            settings = EditingSettings(hook={"text": "hook"})

            def fake_run(command, _label):
                target = Path(command[-1])
                target.write_bytes(b"new-render")
                hook_dir = root / "temp"
                hook_file = next(hook_dir.glob("hook-*.ass"))
                self.assertIn("Dialogue:", hook_file.read_text(encoding="utf-8"))

            with patch("backend.services.smart_editing.run_subprocess", side_effect=fake_run), patch(
                "backend.services.smart_editing.get_media_info",
                return_value={"has_video": True, "has_audio": True, "width": 1080, "height": 1920, "duration": 10},
            ):
                apply_smart_effects(
                    output,
                    settings=settings,
                    duration_seconds=10,
                    config=self.config,
                    has_original_audio=True,
                    temp_dir=root / "temp",
                )
            self.assertEqual(output.read_bytes(), b"new-render")
            self.assertEqual(list((root / "temp").iterdir()), [])

    def test_failed_effect_render_cleans_temporary_files_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "clip.mp4"
            output.write_bytes(b"original")
            with patch("backend.services.smart_editing.run_subprocess", side_effect=RuntimeError("ffmpeg failed")):
                with self.assertRaisesRegex(RuntimeError, "ffmpeg failed"):
                    apply_smart_effects(
                        output,
                        settings=EditingSettings(hook={"text": "hook"}),
                        duration_seconds=10,
                        config=self.config,
                        has_original_audio=True,
                        temp_dir=root / "temp",
                    )
            self.assertEqual(output.read_bytes(), b"original")
            self.assertEqual(list((root / "temp").iterdir()), [])


class TestCompilationCrossfade(unittest.TestCase):
    def _candidates(self, _video_id, candidate_id):
        start = 0 if candidate_id == 1 else 20 if candidate_id == 2 else 40
        return {"id": candidate_id, "start": float(start), "end": float(start + 12)}

    def test_duration_accounting_trims_only_final_segment_after_overlap(self):
        with patch.object(compilation_service, "_candidate_by_id", side_effect=self._candidates), patch.object(
            compilation_service, "get_candidate_editor_state", return_value={}
        ):
            segments, duration = compilation_service.resolve_segments(
                "project123",
                [{"candidate_id": 1}, {"candidate_id": 2}],
                max_total_duration_seconds=22,
                source_duration_seconds=60,
                min_segment_seconds=10,
                max_segment_seconds=60,
                transition_duration_seconds=1,
            )
        self.assertEqual([segment["candidate_id"] for segment in segments], [1, 2])
        self.assertAlmostEqual(segments[-1]["duration"], 11)
        self.assertAlmostEqual(duration, 22)

    def test_crossfade_concat_preserves_segment_order_and_offsets(self):
        command = compilation_service.build_concat_command(
            [Path("one.mp4"), Path("two.mp4"), Path("three.mp4")],
            Path("out.mp4"),
            {"fps": 30, "output_width": 1080, "output_height": 1920},
            has_audio=True,
            transition="crossfade",
            transition_duration_seconds=1,
            segment_durations=[12, 12, 12],
        )
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[0:v:0]", filter_graph)
        self.assertIn("[1:v:0]", filter_graph)
        self.assertIn("[2:v:0]", filter_graph)
        self.assertIn("offset=11.000", filter_graph)
        self.assertIn("offset=22.000", filter_graph)
        self.assertIn("acrossfade=d=1.000", filter_graph)
        self.assertLess(filter_graph.index("[0:v:0]"), filter_graph.index("[1:v:0]"))
        self.assertLess(filter_graph.index("[1:v:0]"), filter_graph.index("[2:v:0]"))

    def test_compilation_output_duration_is_verified_with_rounding_tolerance(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "compiled.mp4"
            output.write_bytes(b"output")
            with patch(
                "backend.services.compilation_service.get_media_info",
                return_value={"has_video": True, "width": 1080, "height": 1920, "duration": 21.8},
            ):
                compilation_service.verify_compilation_output(
                    output,
                    {"output_width": 1080, "output_height": 1920},
                    22,
                )
            with patch(
                "backend.services.compilation_service.get_media_info",
                return_value={"has_video": True, "width": 1080, "height": 1920, "duration": 24},
            ):
                with self.assertRaisesRegex(RuntimeError, "duration"):
                    compilation_service.verify_compilation_output(
                        output,
                        {"output_width": 1080, "output_height": 1920},
                        22,
                    )


class TestMusicAssetOwnership(unittest.TestCase):
    def test_upload_checks_owner_and_records_durable_project_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = []
            with patch.object(music_asset_service, "PROCESSING_TEMP_DIR", root / "temp"), patch.object(
                music_asset_service, "project_owner_id", return_value="owner"
            ), patch.object(music_asset_service, "get_media_info", return_value={"has_audio": True, "duration": 12}), patch.object(
                music_asset_service, "save_music_asset", side_effect=lambda _video, asset: saved.append(asset)
            ), patch.object(music_asset_service, "storage") as storage:
                storage.exists.return_value = False
                result = music_asset_service.upload_music_asset(
                    "project123",
                    owner_id="owner",
                    filename="track.mp3",
                    content_type="audio/mpeg",
                    stream=io.BytesIO(b"audio"),
                )
            self.assertTrue(result["asset_id"].startswith("music-"))
            self.assertNotIn("storage_key", result)
            self.assertTrue(saved[0]["storage_key"].startswith("projects/project123/music/"))
            storage.upload_file.assert_called_once()
            self.assertEqual(list((root / "temp" / "music-uploads").iterdir()), [])

    def test_other_owner_cannot_upload_or_resolve_project_music(self):
        with patch.object(music_asset_service, "project_owner_id", return_value="owner"):
            with self.assertRaises(FileNotFoundError):
                music_asset_service.upload_music_asset(
                    "project123",
                    owner_id="other",
                    filename="track.mp3",
                    content_type="audio/mpeg",
                    stream=io.BytesIO(b"audio"),
                )
        with patch.object(music_asset_service, "find_music_asset", return_value=None):
            with self.assertRaises(FileNotFoundError):
                music_asset_service.download_project_music(
                    "project123",
                    "music-" + "a" * 32,
                    owner_id="other",
                    destination_dir=Path("temp"),
                )

    def test_upload_rejects_unsupported_format_bad_content_and_long_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(music_asset_service, "PROCESSING_TEMP_DIR", Path(directory)), patch.object(
                music_asset_service, "project_owner_id", return_value="owner"
            ):
                with self.assertRaisesRegex(ValueError, "Upload an MP3"):
                    music_asset_service.upload_music_asset(
                        "project123",
                        owner_id="owner",
                        filename="track.exe",
                        content_type="application/octet-stream",
                        stream=io.BytesIO(b"data"),
                    )
                with self.assertRaisesRegex(ValueError, "content type"):
                    music_asset_service.upload_music_asset(
                        "project123",
                        owner_id="owner",
                        filename="track.mp3",
                        content_type="video/mp4",
                        stream=io.BytesIO(b"data"),
                    )
                with patch.object(
                    music_asset_service,
                    "get_media_info",
                    return_value={"has_audio": True, "duration": 1801},
                ):
                    with self.assertRaisesRegex(ValueError, "30 minutes"):
                        music_asset_service.upload_music_asset(
                            "project123",
                            owner_id="owner",
                            filename="track.mp3",
                            content_type="audio/mpeg",
                            stream=io.BytesIO(b"audio"),
                        )

    def test_upload_enforces_byte_limit_without_leaving_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(music_asset_service, "PROCESSING_TEMP_DIR", Path(directory)), patch.object(
                music_asset_service, "project_owner_id", return_value="owner"
            ), patch.object(music_asset_service, "MAX_MUSIC_UPLOAD_BYTES", 4):
                with self.assertRaisesRegex(ValueError, "50 MB or smaller"):
                    music_asset_service.upload_music_asset(
                        "project123",
                        owner_id="owner",
                        filename="track.mp3",
                        content_type="audio/mpeg",
                        stream=io.BytesIO(b"12345"),
                    )
            self.assertEqual(list((Path(directory) / "music-uploads").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
