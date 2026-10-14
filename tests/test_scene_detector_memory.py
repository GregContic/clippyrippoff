from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.detectors import scenes


class _ChunkedPipe:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.max_read_size = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise AssertionError("Scene detection must not read the full output stream.")
        self.max_read_size = max(self.max_read_size, size)
        return self._stream.read(min(size, 17))

    def close(self) -> None:
        self.closed = True
        self._stream.close()


class _FakeProcess:
    def __init__(self, frames: bytes, returncode: int = 0) -> None:
        self.stdout = _ChunkedPipe(frames)
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -1


class TestSceneDetectorMemory(unittest.TestCase):
    def test_streams_raw_frames_and_preserves_scene_scores(self) -> None:
        frame_size = 16 * 16
        first = bytes(frame_size)
        second = bytes([255]) + bytes(frame_size - 1)
        third = second
        process = _FakeProcess(first + second + third)

        with (
            patch.object(scenes, "check_ffmpeg_available"),
            patch.object(scenes.subprocess, "Popen", return_value=process),
        ):
            changes = scenes.detect_scene_changes(
                Path("sample.mp4"),
                sample_fps=1,
                threshold=0.001,
                max_width=16,
            )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].start, 0)
        self.assertEqual(changes[0].end, 1)
        self.assertAlmostEqual(changes[0].change_score, 1 / frame_size)
        self.assertLessEqual(process.stdout.max_read_size, frame_size)
        self.assertTrue(process.stdout.closed)

    def test_terminates_subprocess_when_frame_reading_fails(self) -> None:
        process = _FakeProcess(bytes(16 * 16), returncode=None)
        process.stdout.read = unittest.mock.Mock(side_effect=OSError("pipe failed"))  # type: ignore[method-assign]

        with (
            patch.object(scenes, "check_ffmpeg_available"),
            patch.object(scenes.subprocess, "Popen", return_value=process),
            self.assertRaisesRegex(OSError, "pipe failed"),
        ):
            scenes.detect_scene_changes(Path("sample.mp4"), max_width=16)

        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
