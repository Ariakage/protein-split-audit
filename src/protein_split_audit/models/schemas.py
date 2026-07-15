# SPDX-License-Identifier: Apache-2.0

"""Strict schemas for the frozen classical baselines."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MajorityModelConfig(BaseModel):
    """Training-majority baseline configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    type: Literal["majority"]
    tie_break: Literal["label_lexicographic_ascending"]


class LogisticRegressionModelConfig(BaseModel):
    """Fixed Logistic Regression configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal[1]
    type: Literal["logistic_regression"]
    solver: Literal["lbfgs"]
    penalty: Literal["l2"]
    c: float = Field(alias="C")
    class_weight: Literal["balanced"]
    max_iter: Literal[5000]
    tol: float
    fit_intercept: Literal[True]
    random_state: Literal[42]

    @model_validator(mode="after")
    def require_frozen_floats(self) -> LogisticRegressionModelConfig:
        """Reject numeric changes outside the reviewed protocol."""

        if self.c != 1.0 or self.tol != 0.0001:
            raise ValueError("Logistic Regression floats differ from the frozen protocol")
        return self


class NearestRuntimeConfig(BaseModel):
    """Frozen formal runtime for MMseqs2."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executable: str = "mmseqs"
    cache_root: Path
    timeout_seconds: float = Field(gt=0)
    threads: Literal[8]


class NearestSearchConfig(BaseModel):
    """Frozen v0.2-compatible nearest-homolog predicate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    search_type: Literal[1]
    minimum_coverage: float
    coverage_mode: Literal[0]
    evalue_threshold: float
    sensitivity: float
    alignment_mode: Literal[3]
    sequence_identity_mode: Literal[0]
    minimum_identity: float

    @model_validator(mode="after")
    def require_frozen_floats(self) -> NearestSearchConfig:
        """Reject search values outside the approved v0.2-compatible protocol."""

        observed = (
            self.minimum_coverage,
            self.evalue_threshold,
            self.sensitivity,
            self.minimum_identity,
        )
        if observed != (0.8, 0.001, 7.5, 0.0):
            raise ValueError("nearest-homolog floats differ from the frozen protocol")
        return self


class NoHitConfig(BaseModel):
    """Explicit no-hit fallback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: Literal["training_majority_class"]
    record_explicitly: Literal[True]


HitOrder = tuple[
    Literal["bitscore_desc"],
    Literal["evalue_asc"],
    Literal["percent_identity_desc"],
    Literal["query_coverage_desc"],
    Literal["target_coverage_desc"],
    Literal["target_accession_asc"],
]


class NearestHomologModelConfig(BaseModel):
    """Train-only MMseqs2 nearest-homolog baseline configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    type: Literal["nearest_homolog"]
    engine: Literal["mmseqs2"]
    runtime: NearestRuntimeConfig
    search: NearestSearchConfig
    target_database: Literal["train_only"]
    hit_order: HitOrder
    no_hit: NoHitConfig


ModelConfig = Annotated[
    MajorityModelConfig | LogisticRegressionModelConfig | NearestHomologModelConfig,
    Field(discriminator="type"),
]

__all__ = [
    "LogisticRegressionModelConfig",
    "MajorityModelConfig",
    "ModelConfig",
    "NearestHomologModelConfig",
]
