from __future__ import annotations

import threading
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_MEDIA_WORK_SEMAPHORE = threading.Semaphore(1)


def run_media_task(task: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run one memory-intensive media task at a time in this backend process."""
    with _MEDIA_WORK_SEMAPHORE:
        return task(*args, **kwargs)
