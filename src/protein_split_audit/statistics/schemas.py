# SPDX-License-Identifier: Apache-2.0

"""Strict result schemas for the approved v0.5 statistical families."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

PrimaryMetric = Literal["macro_f1", "balanced_accuracy"]


class IntervalEstimate(BaseModel):
    """One deterministic percentile interval over frozen components."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: PrimaryMetric
    point_estimate: float
    lower: float
    upper: float
    requested_iterations: Literal[2000]
    valid_iterations: Literal[2000]
    confidence_level: float
    group_source: Literal["cluster30_discovery_component"]
    group_count: int
    base_seed: Literal[2026]
    domain: str
    interval_method: Literal["percentile"]
    quantile_method: Literal["linear"]

    @model_validator(mode="after")
    def require_finite_ordered_interval(self) -> IntervalEstimate:
        values = (self.point_estimate, self.lower, self.upper, self.confidence_level)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("statistical interval values must be finite")
        if self.lower > self.upper or self.group_count < 1 or not self.domain:
            raise ValueError("statistical interval identity is invalid")
        if self.confidence_level != 0.95:
            raise ValueError("v0.5 intervals must use 95% confidence")
        return self


class PairedComparisonResult(BaseModel):
    """One approved directed within-split metric difference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    split_name: Literal["random", "cluster70", "cluster50", "cluster30"]
    method_a: str
    method_b: str
    metric: PrimaryMetric
    comparison_type: Literal["absolute_metric_difference"]
    resampling: Literal["paired"]
    point_a: float
    point_b: float
    point_difference: float
    lower: float
    upper: float
    requested_iterations: Literal[2000]
    valid_iterations: Literal[2000]
    group_count: int
    group_source: Literal["cluster30_discovery_component"]
    base_seed: Literal[2026]
    domain: str
    interval_method: Literal["percentile"]

    @model_validator(mode="after")
    def require_finite_directed_difference(self) -> PairedComparisonResult:
        values = (
            self.point_a,
            self.point_b,
            self.point_difference,
            self.lower,
            self.upper,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("paired comparison values must be finite")
        if self.point_difference != self.point_a - self.point_b:
            raise ValueError("paired comparison direction is inconsistent")
        if self.lower > self.upper or self.group_count < 1:
            raise ValueError("paired comparison interval is invalid")
        return self


class GeneralizationGapResult(BaseModel):
    """One independently resampled Random-minus-cluster Macro-F1 gap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str
    reference_split: Literal["random"]
    comparison_split: Literal["cluster70", "cluster50", "cluster30"]
    metric: Literal["macro_f1"]
    resampling: Literal["independent"]
    random_point: float
    cluster_point: float
    point_difference: float
    lower: float
    upper: float
    requested_iterations: Literal[2000]
    valid_iterations: Literal[2000]
    random_group_count: int
    cluster_group_count: int
    group_source: Literal["cluster30_discovery_component"]
    base_seed: Literal[2026]
    domain: str
    interval_method: Literal["percentile"]

    @model_validator(mode="after")
    def require_finite_independent_gap(self) -> GeneralizationGapResult:
        values = (
            self.random_point,
            self.cluster_point,
            self.point_difference,
            self.lower,
            self.upper,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("generalization-gap values must be finite")
        if self.point_difference != self.random_point - self.cluster_point:
            raise ValueError("generalization-gap direction is inconsistent")
        if self.lower > self.upper or min(self.random_group_count, self.cluster_group_count) < 1:
            raise ValueError("generalization-gap interval is invalid")
        return self


__all__ = [
    "GeneralizationGapResult",
    "IntervalEstimate",
    "PairedComparisonResult",
    "PrimaryMetric",
]
