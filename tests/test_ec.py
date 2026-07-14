# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from protein_split_audit.data.ec import parse_ec_annotation


def test_complete_single_ec_maps_to_level_2() -> None:
    result = parse_ec_annotation(" 2.7.11.1 ")

    assert result.ec_number == "2.7.11.1"
    assert result.ec_level_2 == "2.7"
    assert result.rejection_reason is None


@pytest.mark.parametrize("value", ["1.2.3.-", "1.2.3", "1.2.-.-"])
def test_incomplete_ec_is_rejected(value: str) -> None:
    assert parse_ec_annotation(value).rejection_reason == "incomplete_ec"


def test_multiple_ec_values_are_rejected() -> None:
    result = parse_ec_annotation("1.1.1.1; 2.2.2.2")

    assert result.rejection_reason == "multiple_ec"
    assert result.ec_number is None


@pytest.mark.parametrize("value", ["", "not-an-ec", "1.2.3.4.5", "1.2.x.4"])
def test_missing_or_malformed_ec_is_rejected(value: str) -> None:
    expected = "missing_ec" if not value else "malformed_ec"
    assert parse_ec_annotation(value).rejection_reason == expected
