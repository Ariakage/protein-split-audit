# SPDX-License-Identifier: Apache-2.0

"""Strict validation-only experiment schemas."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CohortInput(BaseModel):
    """Frozen cohort paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: Path
    content_manifest: Path
    fasta: Path


class SplitInput(BaseModel):
    """One frozen split input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["random", "cluster70", "cluster50", "cluster30"]
    manifest: Path
    content_manifest: Path


class BaselineDefinition(BaseModel):
    """One fixed baseline and its configuration references."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    name: Literal[
        "majority", "length_logistic", "aac_logistic", "kmer3_logistic", "nearest_homolog"
    ]
    feature_path: Path | None = Field(default=None, alias="feature_config")
    model_path: Path = Field(alias="model_config")


class EvaluationConfig(BaseModel):
    """Validation evaluation or explicitly denied Test request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    split: Literal["validation", "test"]
    label_order_from_cohort: Literal[True]
    zero_division: Literal[0]
    real_test_access_authorized: Literal[False]


class ExperimentRuntimeConfig(BaseModel):
    """Frozen deterministic runtime values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: Literal[42]
    feature_threads: Literal[1]
    mmseqs_threads: Literal[8]


class ExperimentOutputConfig(BaseModel):
    """Local-only run destination policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    refuse_overwrite: Literal[True]


class ExperimentConfig(BaseModel):
    """One fixed five-by-four validation matrix or denied Test request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    cohort: CohortInput
    splits: tuple[SplitInput, ...]
    baselines: tuple[BaselineDefinition, ...]
    evaluation: EvaluationConfig
    runtime: ExperimentRuntimeConfig
    outputs: ExperimentOutputConfig
    attestation: Path | None = None

    @model_validator(mode="after")
    def require_fixed_matrix(self) -> ExperimentConfig:
        """Reject changed matrix membership or an unguarded Test configuration."""

        expected_splits = ("random", "cluster70", "cluster50", "cluster30")
        expected_baselines = (
            "majority",
            "length_logistic",
            "aac_logistic",
            "kmer3_logistic",
            "nearest_homolog",
        )
        if tuple(item.name for item in self.splits) != expected_splits:
            raise ValueError("experiment must declare the four frozen splits in order")
        if tuple(item.name for item in self.baselines) != expected_baselines:
            raise ValueError("experiment must declare the five frozen baselines in order")
        if self.evaluation.split == "test" and self.attestation is None:
            raise ValueError("Test configuration requires an attestation path")
        if self.evaluation.split == "validation" and self.attestation is not None:
            raise ValueError("Validation configuration must not claim a freeze attestation")
        return self


class EsmModelDefinition(BaseModel):
    """One frozen ESM embedding configuration in the v0.4 matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["esm2_35m", "esm2_150m"]
    embedding_config: Path


class EsmExperimentRuntimeConfig(BaseModel):
    """Canonical formal v0.4 runtime values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: Literal[42]
    operating_system: Literal["Darwin"]
    architecture: Literal["arm64"]
    device: Literal["cpu"]
    dtype: Literal["float32"]
    torch_intraop_threads: Literal[8]
    torch_interop_threads: Literal[1]
    deterministic_algorithms: Literal[True]


class EsmExperimentConfig(BaseModel):
    """Exact two-model by four-split Validation matrix or denied Test request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    experiment_type: Literal["esm2_validation"]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    cohort: CohortInput
    splits: tuple[SplitInput, ...]
    models: tuple[EsmModelDefinition, ...]
    linear_probe_config: Path
    evaluation: EvaluationConfig
    runtime: EsmExperimentRuntimeConfig
    outputs: ExperimentOutputConfig
    attestation: Path | None = None

    @property
    def cell_count(self) -> int:
        """Return the frozen matrix size."""

        return len(self.models) * len(self.splits)

    @model_validator(mode="after")
    def require_fixed_matrix(self) -> EsmExperimentConfig:
        """Reject changes to the frozen v0.4 matrix or Test gate."""

        if tuple(item.name for item in self.splits) != (
            "random",
            "cluster70",
            "cluster50",
            "cluster30",
        ):
            raise ValueError("experiment must declare the four frozen splits in order")
        if tuple(item.name for item in self.models) != ("esm2_35m", "esm2_150m"):
            raise ValueError("experiment must declare the two frozen ESM models in order")
        if self.cell_count != 8:
            raise ValueError("v0.4 experiment must contain exactly eight cells")
        if self.evaluation.split == "test" and self.attestation is None:
            raise ValueError("Test configuration requires an attestation path")
        if self.evaluation.split == "validation" and self.attestation is not None:
            raise ValueError("Validation configuration must not claim a freeze attestation")
        return self


__all__ = ["EsmExperimentConfig", "ExperimentConfig"]
