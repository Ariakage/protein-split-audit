# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from protein_split_audit.splits.random_split import SplitMember


def _members() -> tuple[SplitMember, ...]:
    return tuple(SplitMember(f"P{index:02d}", f"{index:064x}", "1.1") for index in range(1, 21))


def test_validate_split_rejects_duplicate_or_missing_members() -> None:
    from protein_split_audit.splits.random_split import create_random_split
    from protein_split_audit.splits.validate import SplitValidationError, validate_split

    members = _members()
    split = create_random_split(members, seed=42)
    duplicate = replace(split, rows=(*split.rows[:-1], split.rows[0]))

    with pytest.raises(SplitValidationError, match="exactly"):
        validate_split(duplicate, expected=members)


def test_validate_split_reports_ratio_and_class_coverage() -> None:
    from protein_split_audit.splits.random_split import create_random_split
    from protein_split_audit.splits.validate import validate_split

    members = _members()
    report = validate_split(create_random_split(members, seed=42), expected=members)

    assert report.valid
    assert report.ratios == {"train": 0.7, "validation": 0.15, "test": 0.15}
