# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.analysis.stratified_metrics import summarize_strata
from tests.v060_analysis_helpers import synthetic_rows


def test_length_summary_uses_absolute_fixed_bins() -> None:
    rows = tuple(
        row
        for length in (50, 200, 400, 600, 800)
        for row in synthetic_rows(5, length=length, component_count=5)
    )
    summary = summarize_strata(rows, dimension="length", include_empty=True)

    assert tuple(dict.fromkeys(item.stratum_id for item in summary)) == (
        "length_050_199",
        "length_200_399",
        "length_400_599",
        "length_600_799",
        "length_800_1000",
    )
    assert all(item.eligibility.sequence_count == 5 for item in summary)
