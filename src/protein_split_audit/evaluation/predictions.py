# SPDX-License-Identifier: Apache-2.0

"""Immutable Validation or capability-gated Test prediction rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
    evaluation_split: Literal["validation", "test"] = "validation"

    def __post_init__(self) -> None:
        if len(self.sequence_sha256) != 32:
            raise ValueError("prediction sequence hash must contain 32 bytes")


__all__ = ["PredictionRow"]
