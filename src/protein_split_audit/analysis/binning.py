# SPDX-License-Identifier: Apache-2.0

"""Result-independent strata for the frozen v0.6 analysis protocol."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BinAssignment:
    """One ordered public stratum identity."""

    order: int
    id: str
    display: str


_EN_DASH = "\N{EN DASH}"
IDENTITY_BINS = (
    BinAssignment(0, "identity_00_20", f"0{_EN_DASH}<20%"),
    BinAssignment(1, "identity_20_30", f"20{_EN_DASH}<30%"),
    BinAssignment(2, "identity_30_40", f"30{_EN_DASH}<40%"),
    BinAssignment(3, "identity_40_50", f"40{_EN_DASH}<50%"),
    BinAssignment(4, "identity_50_70", f"50{_EN_DASH}<70%"),
    BinAssignment(5, "identity_70_100", f"70{_EN_DASH}100%"),
    BinAssignment(6, "no_hit", "No hit"),
)
LENGTH_BINS = (
    BinAssignment(0, "length_050_199", f"50{_EN_DASH}199"),
    BinAssignment(1, "length_200_399", f"200{_EN_DASH}399"),
    BinAssignment(2, "length_400_599", f"400{_EN_DASH}599"),
    BinAssignment(3, "length_600_799", f"600{_EN_DASH}799"),
    BinAssignment(4, "length_800_1000", f"800{_EN_DASH}1000"),
)
COMPONENT_SIZE_BINS = (
    BinAssignment(0, "component_singleton", "1"),
    BinAssignment(1, "component_02_04", f"2{_EN_DASH}4"),
    BinAssignment(2, "component_05_09", f"5{_EN_DASH}9"),
    BinAssignment(3, "component_10_19", f"10{_EN_DASH}19"),
    BinAssignment(4, "component_20_plus", "20+"),
)


def identity_bin(identity: float | None, *, no_hit: bool) -> BinAssignment:
    """Assign exactly one nearest-Train identity stratum."""

    if not isinstance(no_hit, bool):
        raise ValueError("identity no-hit flag must be boolean")
    if no_hit:
        if identity is not None:
            raise ValueError("no-hit identity must be null")
        return IDENTITY_BINS[-1]
    if identity is None or isinstance(identity, bool):
        raise ValueError("hit identity must be finite")
    value = float(identity)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("hit identity must be finite and between zero and one")
    if value < 0.2:
        return IDENTITY_BINS[0]
    if value < 0.3:
        return IDENTITY_BINS[1]
    if value < 0.4:
        return IDENTITY_BINS[2]
    if value < 0.5:
        return IDENTITY_BINS[3]
    if value < 0.7:
        return IDENTITY_BINS[4]
    return IDENTITY_BINS[5]


def length_bin(length: int) -> BinAssignment:
    """Assign one fixed absolute sequence-length stratum."""

    if isinstance(length, bool) or not isinstance(length, int) or not 50 <= length <= 1000:
        raise ValueError("sequence length must be an integer between 50 and 1000")
    if length < 200:
        return LENGTH_BINS[0]
    if length < 400:
        return LENGTH_BINS[1]
    if length < 600:
        return LENGTH_BINS[2]
    if length < 800:
        return LENGTH_BINS[3]
    return LENGTH_BINS[4]


def component_size_bin(size: int) -> BinAssignment:
    """Assign one bin using the component size in the full 442-row cohort."""

    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("component size count must be a positive integer")
    if size == 1:
        return COMPONENT_SIZE_BINS[0]
    if size <= 4:
        return COMPONENT_SIZE_BINS[1]
    if size <= 9:
        return COMPONENT_SIZE_BINS[2]
    if size <= 19:
        return COMPONENT_SIZE_BINS[3]
    return COMPONENT_SIZE_BINS[4]


__all__ = [
    "COMPONENT_SIZE_BINS",
    "IDENTITY_BINS",
    "LENGTH_BINS",
    "BinAssignment",
    "component_size_bin",
    "identity_bin",
    "length_bin",
]
