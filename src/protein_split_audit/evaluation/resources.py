# SPDX-License-Identifier: Apache-2.0

"""Run-specific timing and resident-memory measurements."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread

import psutil  # type: ignore[import-untyped]

SAMPLING_INTERVAL_SECONDS = 0.01


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    """One operation's run-specific resource measurements."""

    elapsed_seconds: float
    peak_rss_bytes: int
    sampling_interval_seconds: float


def _resident_bytes(process: psutil.Process) -> int:
    """Return parent-plus-descendant RSS, tolerating short-lived children."""

    try:
        total = int(process.memory_info().rss)
        children = process.children(recursive=True)
    except (psutil.Error, OSError):
        return 0
    for child in children:
        try:
            total += int(child.memory_info().rss)
        except (psutil.Error, OSError):
            continue
    return total


def measure_call[T](operation: Callable[[], T]) -> tuple[T, ResourceUsage]:
    """Measure one synchronous operation without affecting content identity."""

    process = psutil.Process()
    peak = [_resident_bytes(process)]
    stopped = Event()

    def sample() -> None:
        while not stopped.wait(SAMPLING_INTERVAL_SECONDS):
            peak[0] = max(peak[0], _resident_bytes(process))

    sampler = Thread(target=sample, name="psaudit-resource-sampler", daemon=True)
    started = time.perf_counter_ns()
    sampler.start()
    try:
        result = operation()
    finally:
        stopped.set()
        sampler.join()
        peak[0] = max(peak[0], _resident_bytes(process))
    elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
    return result, ResourceUsage(
        elapsed_seconds=elapsed,
        peak_rss_bytes=peak[0],
        sampling_interval_seconds=SAMPLING_INTERVAL_SECONDS,
    )


__all__ = ["SAMPLING_INTERVAL_SECONDS", "ResourceUsage", "measure_call"]
