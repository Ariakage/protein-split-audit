# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from protein_split_audit.analysis.privacy import group_eligibility


@pytest.mark.parametrize(
    "sequences,components,status,sequence_display,component_display",
    (
        (4, 4, "privacy_suppressed", "<5", "4"),
        (20, 2, "privacy_suppressed", "20", "<3"),
        (4, 2, "privacy_suppressed", "<5", "<3"),
        (5, 3, "insufficient_sequences", "5", "3"),
        (19, 12, "insufficient_sequences", "19", "12"),
        (20, 9, "insufficient_components_for_ci", "20", "9"),
        (20, 10, "reportable", "20", "10"),
    ),
)
def test_threshold_precedence(
    sequences: int,
    components: int,
    status: str,
    sequence_display: str,
    component_display: str,
) -> None:
    observed = group_eligibility(sequences, components)
    assert observed.reporting_status == status
    assert observed.sequence_count_display == sequence_display
    assert observed.component_count_display == component_display
    if status == "privacy_suppressed":
        assert observed.public_sequence_count is None
        assert observed.public_component_count is None
    else:
        assert observed.public_sequence_count == sequences
        assert observed.public_component_count == components


@pytest.mark.parametrize("sequences,components", ((-1, 1), (1, -1), (1, 2)))
def test_eligibility_rejects_impossible_counts(sequences: int, components: int) -> None:
    with pytest.raises(ValueError, match="count"):
        group_eligibility(sequences, components)
