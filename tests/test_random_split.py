# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.splits.random_split import SplitMember


def _members() -> tuple[SplitMember, ...]:
    return tuple(
        SplitMember(
            accession=f"P{label.replace('.', '')}{index:02d}",
            sequence_sha256=f"{offset:064x}",
            ec_level_2=label,
        )
        for offset, (label, index) in enumerate(
            ((label, index) for label in ("1.1", "2.7") for index in range(1, 11)),
            start=1,
        )
    )


def test_create_random_split_is_stratified_deterministic_and_ordered() -> None:
    from protein_split_audit.splits.random_split import create_random_split

    members = _members()
    first = create_random_split(members, seed=42)
    second = create_random_split(tuple(reversed(members)), seed=42)

    assert first == second
    assert first.counts == {"train": 14, "validation": 4, "test": 2}
    assert first.class_counts["1.1"] == {"train": 7, "validation": 2, "test": 1}
    assert first.class_counts["2.7"] == {"train": 7, "validation": 2, "test": 1}
    assert [row.split for row in first.rows] == sorted(
        (row.split for row in first.rows), key={"train": 0, "validation": 1, "test": 2}.get
    )
    assert len({row.sequence_sha256 for row in first.rows}) == len(first.rows)


def test_random_split_seed_changes_assignment() -> None:
    from protein_split_audit.splits.random_split import create_random_split

    assert (
        create_random_split(_members(), seed=42).rows
        != create_random_split(_members(), seed=43).rows
    )
