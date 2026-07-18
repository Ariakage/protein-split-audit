# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

from protein_split_audit.analysis.stratified_metrics import summarize_strata
from tests.v060_analysis_helpers import synthetic_rows


def test_component_size_summary_uses_full_cohort_size_field() -> None:
    sizes = (1, 2, 5, 10, 20)
    rows = tuple(
        replace(row, accession=f"{row.accession}-{size}", component_size=size)
        for size in sizes
        for row in synthetic_rows(5, component_count=5)
    )
    summary = summarize_strata(rows, dimension="component_size", include_empty=True)

    assert tuple(dict.fromkeys(item.stratum_id for item in summary)) == (
        "component_singleton",
        "component_02_04",
        "component_05_09",
        "component_10_19",
        "component_20_plus",
    )
    assert all(item.eligibility.sequence_count == 5 for item in summary)
