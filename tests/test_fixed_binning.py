# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import math

import pytest

from protein_split_audit.analysis.binning import (
    component_size_bin,
    identity_bin,
    length_bin,
)


@pytest.mark.parametrize(
    "value,expected",
    (
        (0.0, "identity_00_20"),
        (math.nextafter(0.2, 0.0), "identity_00_20"),
        (0.2, "identity_20_30"),
        (0.3, "identity_30_40"),
        (0.4, "identity_40_50"),
        (0.5, "identity_50_70"),
        (0.7, "identity_70_100"),
        (1.0, "identity_70_100"),
    ),
)
def test_identity_boundaries(value: float, expected: str) -> None:
    assert identity_bin(value, no_hit=False).id == expected


def test_no_hit_is_a_distinct_null_identity_bin() -> None:
    assert identity_bin(None, no_hit=True).id == "no_hit"
    with pytest.raises(ValueError, match="no-hit identity"):
        identity_bin(0.0, no_hit=True)
    with pytest.raises(ValueError, match="hit identity"):
        identity_bin(None, no_hit=False)


@pytest.mark.parametrize("value", (-0.1, 1.01, math.nan, math.inf, -math.inf))
def test_identity_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError, match="identity"):
        identity_bin(value, no_hit=False)


@pytest.mark.parametrize(
    "value,expected",
    (
        (50, "length_050_199"),
        (199, "length_050_199"),
        (200, "length_200_399"),
        (399, "length_200_399"),
        (400, "length_400_599"),
        (599, "length_400_599"),
        (600, "length_600_799"),
        (799, "length_600_799"),
        (800, "length_800_1000"),
        (1000, "length_800_1000"),
    ),
)
def test_length_boundaries(value: int, expected: str) -> None:
    assert length_bin(value).id == expected


@pytest.mark.parametrize("value", (49, 1001, True, 50.0))
def test_length_rejects_out_of_protocol_values(value: object) -> None:
    with pytest.raises(ValueError, match="length"):
        length_bin(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value,expected",
    (
        (1, "component_singleton"),
        (2, "component_02_04"),
        (4, "component_02_04"),
        (5, "component_05_09"),
        (9, "component_05_09"),
        (10, "component_10_19"),
        (19, "component_10_19"),
        (20, "component_20_plus"),
        (442, "component_20_plus"),
    ),
)
def test_component_size_boundaries(value: int, expected: str) -> None:
    assert component_size_bin(value).id == expected
