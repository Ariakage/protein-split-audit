# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


def test_resource_measurement_records_sampling_policy() -> None:
    from protein_split_audit.evaluation.resources import measure_call

    value, usage = measure_call(lambda: bytearray(1024 * 1024))

    assert len(value) == 1024 * 1024
    assert usage.elapsed_seconds >= 0.0
    assert usage.peak_rss_bytes > 0
    assert usage.sampling_interval_seconds == 0.01
