# SPDX-License-Identifier: Apache-2.0

"""Aggregate-only Nearest Homolog failure-mode analysis."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from protein_split_audit.analysis.inputs import AnalysisRow


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    """Fixed descriptive statistics for accepted nearest hits."""

    minimum: float | None
    median: float | None
    mean: float | None
    p90: float | None
    p95: float | None
    maximum: float | None


@dataclass(frozen=True, slots=True)
class NearestHomologSummary:
    """Sequence-free failure-mode facts for one split."""

    total_count: int
    hit_count: int
    no_hit_count: int
    fallback_count: int
    no_hit_correct_count: int
    same_label_hit_count: int
    different_label_hit_count: int
    identity: DistributionSummary
    query_coverage: DistributionSummary
    target_coverage: DistributionSummary
    bitscore: DistributionSummary


def _distribution(values: Sequence[float]) -> DistributionSummary:
    observed = tuple(float(value) for value in values)
    if not observed:
        return DistributionSummary(None, None, None, None, None, None)
    if not all(math.isfinite(value) for value in observed):
        raise ValueError("nearest-homolog distributions require finite values")
    array = np.asarray(observed, dtype=np.float64)
    p90, p95 = np.quantile(array, [0.9, 0.95], method="linear")
    return DistributionSummary(
        minimum=min(observed),
        median=float(statistics.median(observed)),
        mean=float(statistics.fmean(observed)),
        p90=float(p90),
        p95=float(p95),
        maximum=max(observed),
    )


def _validate_row(row: AnalysisRow) -> None:
    if row.method != "nearest-homolog":
        raise ValueError("nearest-homolog analysis accepts only its frozen method rows")
    neighbor = (
        row.nearest_train_accession,
        row.nearest_train_label,
        row.query_coverage,
        row.target_coverage,
        row.bitscore,
        row.evalue,
    )
    if row.no_hit:
        if row.nearest_train_identity is not None or any(value is not None for value in neighbor):
            raise ValueError("no-hit neighbor metadata must be entirely null")
        return
    if row.nearest_train_identity is None or any(value is None for value in neighbor):
        raise ValueError("accepted hit requires complete neighbor metadata")
    identity = float(row.nearest_train_identity)
    query = float(row.query_coverage)  # type: ignore[arg-type]
    target = float(row.target_coverage)  # type: ignore[arg-type]
    bitscore = float(row.bitscore)  # type: ignore[arg-type]
    evalue = float(row.evalue)  # type: ignore[arg-type]
    if not all(math.isfinite(value) for value in (identity, query, target, bitscore, evalue)):
        raise ValueError("accepted hit violates the frozen predicate")
    if not (
        0.0 <= identity <= 1.0
        and 0.8 <= query <= 1.0
        and 0.8 <= target <= 1.0
        and 0.0 <= evalue <= 0.001
        and bitscore >= 0.0
    ):
        raise ValueError("accepted hit violates the frozen predicate")
    if row.nearest_train_label != row.predicted_label:
        raise ValueError("accepted hit prediction must equal the nearest Train label")


def summarize_nearest_homolog(rows: Sequence[AnalysisRow]) -> NearestHomologSummary:
    """Validate and aggregate one split's frozen nearest-neighbor details."""

    records = tuple(rows)
    if not records:
        raise ValueError("nearest-homolog analysis requires at least one row")
    if len({row.split_name for row in records}) != 1:
        raise ValueError("nearest-homolog summary requires one split")
    for row in records:
        _validate_row(row)
    hits = tuple(row for row in records if not row.no_hit)
    no_hits = tuple(row for row in records if row.no_hit)
    same = sum(row.nearest_train_label == row.true_label for row in hits)
    return NearestHomologSummary(
        total_count=len(records),
        hit_count=len(hits),
        no_hit_count=len(no_hits),
        fallback_count=len(no_hits),
        no_hit_correct_count=sum(row.correct for row in no_hits),
        same_label_hit_count=same,
        different_label_hit_count=len(hits) - same,
        identity=_distribution(
            tuple(float(row.nearest_train_identity) for row in hits)  # type: ignore[arg-type]
        ),
        query_coverage=_distribution(
            tuple(float(row.query_coverage) for row in hits)  # type: ignore[arg-type]
        ),
        target_coverage=_distribution(
            tuple(float(row.target_coverage) for row in hits)  # type: ignore[arg-type]
        ),
        bitscore=_distribution(
            tuple(float(row.bitscore) for row in hits)  # type: ignore[arg-type]
        ),
    )


__all__ = [
    "DistributionSummary",
    "NearestHomologSummary",
    "summarize_nearest_homolog",
]
