# SPDX-License-Identifier: Apache-2.0

"""Shared Train-only row selection helpers."""

from __future__ import annotations

from collections.abc import Sequence

from protein_split_audit.features.validation import SequenceRecord


def training_labels(records: Sequence[SequenceRecord]) -> tuple[str, ...]:
    """Return labels for Train rows only."""

    return tuple(record.label for record in records if record.split == "train")


__all__ = ["training_labels"]
