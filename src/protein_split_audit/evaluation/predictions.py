# SPDX-License-Identifier: Apache-2.0

"""Immutable validation prediction rows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PredictionRow:
    """One Validation prediction in frozen score order."""

    accession: str
    sequence_sha256: bytes
    split_name: str
    true_label: str
    predicted_label: str
    scores: tuple[float, ...]
    nearest_train_identity: float | None
    no_hit: bool | None
    evaluation_split: str = "validation"

    def __post_init__(self) -> None:
        if self.evaluation_split != "validation":
            raise ValueError("v0.3 predictions must belong to Validation")
        if len(self.sequence_sha256) != 32:
            raise ValueError("prediction sequence hash must contain 32 bytes")


__all__ = ["PredictionRow"]
