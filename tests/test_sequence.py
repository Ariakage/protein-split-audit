# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from protein_split_audit.data.sequence import validate_sequence


def test_sequence_is_stripped_uppercased_and_hashed() -> None:
    result = validate_sequence(f"  {'acde' * 13}  ", min_length=50, max_length=1000)

    assert result.sequence == ("ACDE" * 13)
    assert result.sequence_length == 52
    assert result.sequence_sha256 is not None
    assert result.rejection_reason is None


@pytest.mark.parametrize("sequence", ["A" * 49 + "B", "A" * 49 + "*", "A" * 25 + " " + "A" * 25])
def test_nonstandard_sequence_characters_are_rejected(sequence: str) -> None:
    assert (
        validate_sequence(sequence, min_length=50, max_length=1000).rejection_reason
        == "invalid_sequence_characters"
    )


@pytest.mark.parametrize("length", [50, 1000])
def test_inclusive_length_boundaries_are_valid(length: int) -> None:
    result = validate_sequence("W" * length, min_length=50, max_length=1000)

    assert result.sequence_length == length
    assert result.rejection_reason is None


@pytest.mark.parametrize(
    ("length", "reason"),
    [(49, "sequence_too_short"), (1001, "sequence_too_long")],
)
def test_out_of_range_lengths_are_rejected(length: int, reason: str) -> None:
    result = validate_sequence("A" * length, min_length=50, max_length=1000)

    assert result.rejection_reason == reason
