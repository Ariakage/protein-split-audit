# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.analysis.stratified_metrics import summarize_strata
from tests.v060_analysis_helpers import synthetic_rows


def test_identity_summary_uses_fixed_order_and_no_hit() -> None:
    rows = (
        *synthetic_rows(20, identity=0.19, component_count=10),
        *synthetic_rows(5, identity=None, no_hit=True, component_count=5),
    )
    summary = summarize_strata(rows, dimension="identity", include_empty=True)

    assert tuple(dict.fromkeys(item.stratum_id for item in summary)) == (
        "identity_00_20",
        "identity_20_30",
        "identity_30_40",
        "identity_40_50",
        "identity_50_70",
        "identity_70_100",
        "no_hit",
    )
    no_hit = [item for item in summary if item.stratum_id == "no_hit"]
    assert {item.eligibility.sequence_count for item in no_hit} == {5}


def test_identity_metrics_follow_threshold_precedence() -> None:
    rows = synthetic_rows(20, identity=0.2, component_count=9)
    summary = summarize_strata(rows, dimension="identity", include_empty=False)

    assert len(summary) == 3
    assert {item.eligibility.reporting_status for item in summary} == {
        "insufficient_components_for_ci"
    }
    assert all(item.estimate is not None and item.ci_lower is None for item in summary)
