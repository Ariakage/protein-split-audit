# SPDX-License-Identifier: Apache-2.0

"""Deterministic training-majority baseline."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MajorityModel:
    """One fitted majority label and its sorted Train counts."""

    label: str
    counts: tuple[tuple[str, int], ...]

    def predict(self, count: int) -> tuple[str, ...]:
        """Predict the fitted label a fixed number of times."""

        if count < 0:
            raise ValueError("prediction count must be non-negative")
        return (self.label,) * count


def fit_majority(labels: Sequence[str]) -> MajorityModel:
    """Fit Train label counts with lexical tie-breaking."""

    if not labels:
        raise ValueError("majority baseline requires at least one Train label")
    counter = Counter(labels)
    largest = max(counter.values())
    label = min(candidate for candidate, count in counter.items() if count == largest)
    return MajorityModel(label=label, counts=tuple(sorted(counter.items())))


__all__ = ["MajorityModel", "fit_majority"]
