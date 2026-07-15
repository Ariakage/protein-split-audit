# SPDX-License-Identifier: Apache-2.0

"""Deterministic sequence-stratified Random Split construction."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from protein_split_audit.splits.allocator import FIXED_RATIOS, allocate_ratio_counts

type SplitName = Literal["train", "validation", "test"]
_SPLIT_NAMES: tuple[SplitName, ...] = ("train", "validation", "test")
_EC_PATTERN = re.compile(r"^\d+\.\d+$")


class RandomSplitError(ValueError):
    """Raised when deterministic split inputs violate the protocol."""


@dataclass(frozen=True, slots=True)
class SplitMember:
    """Minimal exact identity required by every split strategy."""

    accession: str
    sequence_sha256: str
    ec_level_2: str

    def __post_init__(self) -> None:
        if not self.accession or self.accession.strip() != self.accession:
            raise RandomSplitError("split accession must be non-empty without surrounding space")
        try:
            valid_hash = (
                len(self.sequence_sha256) == 64
                and bytes.fromhex(self.sequence_sha256).hex() == self.sequence_sha256
            )
        except ValueError:
            valid_hash = False
        if not valid_hash:
            raise RandomSplitError("split sequence hash must be lowercase SHA-256")
        if _EC_PATTERN.fullmatch(self.ec_level_2) is None:
            raise RandomSplitError("split EC label must contain exactly two integers")


@dataclass(frozen=True, slots=True)
class SplitRow:
    """One deterministic split membership row."""

    member: SplitMember
    split: SplitName
    component_id: str | None = None

    @property
    def accession(self) -> str:
        return self.member.accession

    @property
    def sequence_sha256(self) -> str:
        return self.member.sequence_sha256

    @property
    def ec_level_2(self) -> str:
        return self.member.ec_level_2


@dataclass(frozen=True, slots=True)
class SplitAssignment:
    """Complete deterministic assignment and aggregate counts."""

    name: str
    strategy: str
    seed: int
    rows: tuple[SplitRow, ...]
    counts: dict[str, int]
    class_counts: dict[str, dict[str, int]]


def _ec_key(label: str) -> tuple[int, int, str]:
    first, second = label.split(".")
    return int(first), int(second), label


def _rank(seed: int, member: SplitMember) -> tuple[bytes, str, str]:
    digest = hashlib.sha256(
        f"{seed}\n{member.accession}\n{member.sequence_sha256}".encode()
    ).digest()
    return digest, member.accession, member.sequence_sha256


def _class_counts(total: int) -> tuple[int, int, int]:
    counts = allocate_ratio_counts(total, FIXED_RATIOS).as_tuple()
    if total >= 3 and 0 in counts:
        return total - 2, 1, 1
    return counts


def create_random_split(
    cohort: Sequence[SplitMember],
    *,
    seed: int = 42,
) -> SplitAssignment:
    """Assign each class independently by the frozen SHA-256 ranking rule."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RandomSplitError("split seed must be an integer")
    members = tuple(cohort)
    if not members:
        raise RandomSplitError("cohort must contain at least one member")
    if len({member.accession for member in members}) != len(members) or len(
        {member.sequence_sha256 for member in members}
    ) != len(members):
        raise RandomSplitError("cohort contains duplicate accession or exact sequence hash")

    by_class: dict[str, list[SplitMember]] = defaultdict(list)
    for member in members:
        by_class[member.ec_level_2].append(member)
    rows: list[SplitRow] = []
    for label in sorted(by_class, key=_ec_key):
        ordered = sorted(by_class[label], key=lambda member: _rank(seed, member))
        train_count, validation_count, _ = _class_counts(len(ordered))
        for index, member in enumerate(ordered):
            split: SplitName
            if index < train_count:
                split = "train"
            elif index < train_count + validation_count:
                split = "validation"
            else:
                split = "test"
            rows.append(SplitRow(member=member, split=split))

    split_order = {name: index for index, name in enumerate(_SPLIT_NAMES)}
    ordered_rows = tuple(
        sorted(
            rows,
            key=lambda row: (
                split_order[row.split],
                _ec_key(row.ec_level_2),
                row.accession,
                row.sequence_sha256,
            ),
        )
    )
    counts = Counter(row.split for row in ordered_rows)
    class_counts: dict[str, dict[str, int]] = {
        label: {
            name: sum(row.split == name for row in ordered_rows if row.ec_level_2 == label)
            for name in _SPLIT_NAMES
        }
        for label in sorted(by_class, key=_ec_key)
    }
    return SplitAssignment(
        name="random",
        strategy="sequence_stratified",
        seed=seed,
        rows=ordered_rows,
        counts={name: counts[name] for name in _SPLIT_NAMES},
        class_counts=class_counts,
    )


__all__ = [
    "RandomSplitError",
    "SplitAssignment",
    "SplitMember",
    "SplitName",
    "SplitRow",
    "create_random_split",
]
