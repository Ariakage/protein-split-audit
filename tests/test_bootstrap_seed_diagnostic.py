# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.analysis.robustness import seed_diagnostic


def test_seed_diagnostic_reports_endpoint_and_width_shifts() -> None:
    result = seed_diagnostic(
        primary=(0.1, 0.5),
        alternatives=((3407, 0.08, 0.55), (42, 0.15, 0.49)),
    )

    assert result.primary_seed == 2026
    assert result.diagnostic_seeds == (3407, 42)
    assert result.maximum_lower_shift == 0.05
    assert result.maximum_upper_shift == 0.05
    assert result.maximum_width_shift == 0.07
    assert result.pass_fail is None
