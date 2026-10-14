from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.services.media_concurrency import run_media_task


class TestMediaConcurrency(unittest.TestCase):
    def test_media_tasks_do_not_overlap(self) -> None:
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()

        def first() -> str:
            first_started.set()
            if not release_first.wait(timeout=2):
                raise TimeoutError("The test did not release the first media task.")
            return "first"

        def second() -> str:
            second_started.set()
            return "second"

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(run_media_task, first)
            self.assertTrue(first_started.wait(timeout=2))
            second_future = executor.submit(run_media_task, second)
            self.assertFalse(second_started.wait(timeout=0.05))
            release_first.set()
            self.assertEqual(first_future.result(timeout=2), "first")
            self.assertEqual(second_future.result(timeout=2), "second")

        self.assertTrue(second_started.is_set())


if __name__ == "__main__":
    unittest.main()
