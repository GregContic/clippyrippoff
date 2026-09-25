"""Pure-Python V2 detector tests; no real video or FFmpeg required."""
import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from tests import SCRIPTS_DIR  # noqa: F401
import detect_clips
from detectors.audio import detect_audio_peaks
from detectors.transcript import detect_transcript_triggers
from detect_clips import CandidateWindow, _select_non_overlapping, build_candidate_windows, score_candidate


class TestTranscriptDetector(unittest.TestCase):
    def test_keywords_are_case_insensitive(self):
        triggers = detect_transcript_triggers(
            [{"start": 10, "end": 12, "text": "NO WAY HE DID THAT!"}],
            ["no way"],
        )
        self.assertEqual(triggers[0].matched_keywords, ["no way"])
        self.assertGreater(triggers[0].score, 0)

    def test_unrelated_segment_is_not_triggered(self):
        self.assertEqual(
            detect_transcript_triggers(
                [{"start": 1, "end": 3, "text": "move to the next room"}], ["no way"]
            ),
            [],
        )


class TestAudioDetector(unittest.TestCase):
    def test_detects_local_rms_spike(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.wav"
            sample_rate = 1000
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                for index in range(4000):
                    amplitude = 30000 if 1500 <= index < 1750 else 1000
                    wav_file.writeframes(int(amplitude).to_bytes(2, "little", signed=True))
            peaks = detect_audio_peaks(
                path, window_seconds=0.25, baseline_seconds=2, relative_threshold=1.8, min_peak=0.02
            )
            self.assertTrue(peaks)
            self.assertTrue(any(1.5 <= peak.start <= 1.75 for peak in peaks))


class TestCandidateWindows(unittest.TestCase):
    @staticmethod
    def _trigger(start=10.0, end=11.0, strength="medium"):
        return type("Trigger", (), {"start": start, "end": end, "score": 1.0, "strength": strength})()

    def test_nearby_signals_merge_and_respect_bounds(self):
        windows = build_candidate_windows(
            [],
            [
                type("Peak", (), {"start": 10.0, "end": 10.5})(),
                type("Peak", (), {"start": 12.0, "end": 12.5})(),
            ],
            [],
            video_duration=100,
            min_seconds=10,
            max_seconds=60,
            before_seconds=7,
            after_seconds=8,
            merge_gap_seconds=3,
        )
        self.assertEqual(len(windows), 1)
        self.assertGreaterEqual(windows[0].end - windows[0].start, 10)
        self.assertLessEqual(windows[0].end - windows[0].start, 60)

    def test_events_without_enough_context_are_dropped(self):
        windows = build_candidate_windows(
            [type("Trigger", (), {"start": 5.0, "end": 5.2})()], [], [],
            video_duration=7,
            min_seconds=10,
            max_seconds=60,
            before_seconds=1,
            after_seconds=1,
            merge_gap_seconds=1,
        )
        self.assertEqual(windows, [])

    def test_clustered_signals_make_one_natural_trigger_centered_window(self):
        trigger = type("Trigger", (), {"start": 50.0, "end": 51.0, "score": 1.0})()
        peak = type("Peak", (), {"start": 51.5, "end": 52.0, "relative_peak": 4.0})()
        scene = type("Scene", (), {"start": 53.0, "end": 53.2, "change_score": 0.8})()
        windows = build_candidate_windows(
            [trigger], [peak], [scene], 100, 10, 60, 5, 8, 3
        )
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].trigger_types, ["audio_peak", "reaction", "scene_change"])
        self.assertGreater(windows[0].trigger_time, windows[0].start)
        self.assertLess(windows[0].trigger_time, windows[0].end)
        self.assertLess(windows[0].end - windows[0].start, 60)

    def test_short_natural_window_expands_to_minimum(self):
        windows = build_candidate_windows(
            [], [type("Peak", (), {"start": 30.0, "end": 30.2, "relative_peak": 3.0})()],
            [], 100, 10, 60, 1, 1, 1
        )
        self.assertEqual(len(windows), 1)
        self.assertAlmostEqual(windows[0].end - windows[0].start, 10)

    def test_window_never_exceeds_maximum(self):
        windows = build_candidate_windows(
            [type("Trigger", (), {"start": 50.0, "end": 51.0, "score": 1.0})()],
            [], [], 100, 10, 12, 10, 10, 1
        )
        self.assertEqual(len(windows), 1)
        self.assertLessEqual(windows[0].end - windows[0].start, 12)

    def test_edges_can_align_to_transcript_segments(self):
        windows = build_candidate_windows(
            [type("Trigger", (), {"start": 50.0, "end": 51.0, "score": 1.0})()],
            [], [], 100, 10, 60, 5, 8, 1,
            transcript_segments=[{"start": 44.0, "end": 47.0}, {"start": 47.0, "end": 52.0}, {"start": 52.0, "end": 60.0}],
        )
        self.assertEqual(windows[0].start, 44.0)
        self.assertEqual(windows[0].end, 60.0)

    def test_trigger_in_middle_of_sentence_uses_sentence_start(self):
        window = build_candidate_windows(
            [self._trigger()], [], [], 100, 3, 30, 5, 8, 1,
            [{"start": 7, "end": 13, "text": "Here is the setup, wait, what happened?"}],
        )[0]
        self.assertEqual(window.start, 7)
        self.assertEqual(window.start_reason, "sentence_start")

    def test_clear_setup_is_included_but_unrelated_gap_is_not(self):
        setup = build_candidate_windows(
            [self._trigger()], [], [], 100, 3, 30, 5, 5, 1,
            [{"start": 5, "end": 8, "text": "Watch this setup"}, {"start": 8, "end": 11, "text": "Wait what?"}],
        )[0]
        unrelated = build_candidate_windows(
            [self._trigger()], [], [], 100, 3, 30, 5, 5, 1,
            [{"start": 1, "end": 3, "text": "Unrelated conversation"}, {"start": 10, "end": 11, "text": "Wait what?"}],
        )[0]
        self.assertEqual(setup.start, 5)
        self.assertGreaterEqual(unrelated.start, 9)
        self.assertGreater(unrelated.start, setup.start)

    def test_payoff_is_kept_and_quick_payoff_trims_quiet(self):
        extended = build_candidate_windows(
            [self._trigger()], [], [], 100, 3, 30, 2, 8, 1,
            [{"start": 10, "end": 11, "text": "What?"}, {"start": 11.3, "end": 16, "text": "That was the payoff"}],
        )[0]
        quick = build_candidate_windows(
            [self._trigger()], [], [], 100, 3, 30, 2, 8, 1,
            [{"start": 10, "end": 11, "text": "What?"}],
        )[0]
        self.assertEqual(extended.end, 16)
        self.assertEqual(extended.end_reason, "payoff_speech")
        self.assertLess(quick.end, 15)
        self.assertEqual(quick.end_reason, "quiet_boundary")

    def test_significant_scene_transition_ends_after_payoff(self):
        scene = type("Scene", (), {"start": 12.0, "end": 12.5, "change_score": 0.6})()
        window = build_candidate_windows(
            [self._trigger()], [], [scene], 100, 3, 30, 2, 12, 3,
            [{"start": 10, "end": 11, "text": "What happened?"}],
        )[0]
        self.assertAlmostEqual(window.end, 12.75)
        self.assertEqual(window.end_reason, "scene_transition_after_payoff")

    def test_related_trigger_after_scene_suppresses_transition_end(self):
        scene = type("Scene", (), {"start": 12.0, "end": 12.5, "change_score": 0.6})()
        triggers = [self._trigger(), self._trigger(13.0, 14.0, "medium")]
        window = build_candidate_windows(
            triggers, [], [scene], 100, 3, 30, 2, 12, 3,
            [{"start": 10, "end": 11, "text": "What happened?"}, {"start": 13, "end": 14, "text": "What?"}],
        )[0]
        self.assertNotEqual(window.end_reason, "scene_transition_after_payoff")
        self.assertGreater(window.end, scene.end)

    def test_small_scene_change_does_not_force_early_end(self):
        scene = type("Scene", (), {"start": 12.0, "end": 12.5, "change_score": 0.2})()
        window = build_candidate_windows(
            [self._trigger()], [], [scene], 100, 3, 30, 2, 12, 3,
            [{"start": 10, "end": 11, "text": "What happened?"}],
        )[0]
        self.assertNotEqual(window.end_reason, "scene_transition_after_payoff")
        self.assertGreater(window.end, scene.end)

    def test_scene_change_during_active_payoff_does_not_cut_payoff(self):
        scene = type("Scene", (), {"start": 12.0, "end": 12.5, "change_score": 0.8})()
        window = build_candidate_windows(
            [self._trigger()], [], [scene], 100, 3, 30, 2, 12, 3,
            [{"start": 10, "end": 15, "text": "What happened and then it kept going?"}],
        )[0]
        self.assertGreaterEqual(window.end, 15)
        self.assertNotEqual(window.end_reason, "scene_transition_after_payoff")

    def test_scene_change_after_payoff_ends_even_after_payoff_continuation(self):
        scene = type("Scene", (), {"start": 16.0, "end": 17.0, "change_score": 0.8})()
        window = build_candidate_windows(
            [self._trigger()], [], [scene], 100, 3, 30, 2, 12, 3,
            [{"start": 10, "end": 11, "text": "What happened?"}, {"start": 11.2, "end": 16, "text": "That was the payoff"}],
        )[0]
        self.assertLessEqual(window.end, 16.75)
        self.assertEqual(window.end_reason, "scene_transition_after_payoff")

    def test_strong_reaction_gets_more_context_than_weak_reaction(self):
        payoff_peak = type("Peak", (), {"start": 12.0, "end": 12.5, "relative_peak": 3.0})()
        weak = build_candidate_windows(
            [self._trigger(strength="weak")], [payoff_peak], [], 100, 1, 30, 5, 8, 1,
        )[0]
        strong = build_candidate_windows(
            [self._trigger(strength="strong")], [payoff_peak], [], 100, 1, 30, 5, 8, 1,
        )[0]
        self.assertGreater(strong.setup_seconds, weak.setup_seconds)
        self.assertGreater(strong.payoff_seconds, weak.payoff_seconds)

    def test_event_aware_window_respects_minimum_and_maximum(self):
        minimum = build_candidate_windows(
            [self._trigger()], [], [], 100, 10, 60, 1, 1, 1,
        )[0]
        maximum = build_candidate_windows(
            [self._trigger()], [], [], 100, 10, 12, 20, 20, 1,
        )[0]
        self.assertGreaterEqual(minimum.end - minimum.start, 10)
        self.assertLessEqual(maximum.end - maximum.start, 12)

    def test_diagnostics_are_populated_for_backward_compatible_doubles(self):
        window = build_candidate_windows(
            [], [type("Peak", (), {"start": 10, "end": 10.2})()], [], 100, 3, 30, 2, 2, 1,
        )[0]
        candidate = score_candidate(window, [], [], [])
        self.assertIn(candidate["start_reason"], {"quiet_boundary", "trigger_context"})
        self.assertIsNotNone(candidate["setup_seconds"])

    def test_final_event_windows_still_suppress_overlap(self):
        windows = [
            {"start": 10, "end": 20, "candidate_score": 90},
            {"start": 18, "end": 25, "candidate_score": 80},
        ]
        self.assertEqual(_select_non_overlapping(windows), [windows[0]])


class TestCandidateScoring(unittest.TestCase):
    def test_score_contains_explainable_signal_components(self):
        trigger = type(
            "Trigger", (), {"start": 10.0, "end": 12.0, "text": "NO WAY", "matched_keywords": ["no way"], "score": 1.0}
        )()
        peak = type("Peak", (), {"start": 10.0, "end": 11.0, "peak": 0.5, "relative_peak": 3.0})()
        candidate = score_candidate(CandidateWindow(3, 20), [trigger], [peak], [])
        self.assertEqual(candidate["candidate_score"], 67)
        self.assertEqual(candidate["signals"]["reaction_score"], 15)
        self.assertTrue(candidate["reaction_detected"])

    def test_reaction_strength_changes_reaction_score(self):
        scores = {"weak": 3, "medium": 8, "strong": 15}
        candidates = []
        for strength in ("weak", "medium", "strong"):
            trigger = type(
                "Trigger", (), {"start": 10.0, "end": 12.0, "text": strength, "matched_keywords": [strength], "score": 0.5, "strength": strength}
            )()
            candidates.append(score_candidate(CandidateWindow(5, 20), [trigger], [], [], scores))
        self.assertEqual([candidate["signals"]["reaction_score"] for candidate in candidates], [3, 8, 15])

    def test_weak_generic_keyword_is_not_high_scoring(self):
        triggers = detect_transcript_triggers(
            [{"start": 10, "end": 11, "text": "what"}],
            {"weak": ["what"], "medium": ["bro"], "strong": ["oh my god"]},
        )
        candidate = score_candidate(CandidateWindow(5, 20), triggers, [], [])
        self.assertEqual(triggers[0].strength, "weak")
        self.assertLess(candidate["candidate_score"], 15)

    def test_overlapping_candidates_keep_highest_ranked_candidate(self):
        candidates = [
            {"start": 10.0, "end": 20.0, "candidate_score": 90},
            {"start": 19.0, "end": 25.0, "candidate_score": 80},
            {"start": 30.0, "end": 35.0, "candidate_score": 70},
        ]
        self.assertEqual(_select_non_overlapping(candidates), [candidates[0], candidates[2]])


class TestDetectCli(unittest.TestCase):
    @staticmethod
    def _candidates(count: int) -> list[dict]:
        return [
            {
                "id": index,
                "start": float(index),
                "end": float(index + 10),
                "duration": 10.0,
                "candidate_score": 100 - index,
                "transcript": "",
                "signals": {},
                "audio_peak": 0.0,
                "relative_audio_peak": 0.0,
                "audio_level": "NONE",
                "reaction_detected": False,
                "matched_keywords": [],
                "scene_change_score": 0.0,
            }
            for index in range(1, count + 1)
        ]

    def _run_main(self, top: int | None, max_candidates: int = 20) -> list[dict]:
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "video.mp4"
            output_path = Path(directory) / "candidates.json"
            video_path.touch()
            arguments = ["--video", str(video_path)]
            if top is not None:
                arguments.extend(["--top", str(top)])
            with patch.object(detect_clips, "ensure_directories"), patch.object(
                detect_clips, "load_config", return_value={"max_candidates": max_candidates}
            ), patch.object(
                detect_clips, "detect_candidates", return_value=self._candidates(12)
            ), patch.object(
                detect_clips, "candidates_path_for_video", return_value=output_path
            ), patch.object(detect_clips, "print_candidates"):
                self.assertEqual(detect_clips.main(arguments), 0)
            return json.loads(output_path.read_text(encoding="utf-8"))["candidates"]

    def test_default_uses_configured_max_candidates(self):
        self.assertEqual(len(self._run_main(None, max_candidates=2)), 2)

    def test_top_one_limits_json_output(self):
        self.assertEqual(len(self._run_main(1)), 1)

    def test_top_ten_limits_json_output(self):
        self.assertEqual(len(self._run_main(10)), 10)

    def test_top_zero_is_rejected(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as error, contextlib.redirect_stderr(stderr):
            detect_clips.build_parser().parse_args(["--top", "0"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("must be at least 1", stderr.getvalue())

    def test_top_non_integer_is_rejected(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as error, contextlib.redirect_stderr(stderr):
            detect_clips.build_parser().parse_args(["--top", "many"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("must be an integer", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
