# SPDX-License-Identifier: Apache-2.0

"""Strict validation-only experiment schemas."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

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


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitRevision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
FrozenMethodName = Literal[
    "majority",
    "length_logistic",
    "aac_logistic",
    "kmer3_logistic",
    "nearest_homolog",
    "esm2_35m",
    "esm2_150m",
]
FrozenSplitName = Literal["random", "cluster70", "cluster50", "cluster30"]


class FrozenCohortInput(BaseModel):
    """Exact frozen cohort identities required by v0.5."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: Path
    file_sha256: Sha256
    semantic_sha256: Sha256
    content_manifest: Path
    content_manifest_sha256: Sha256
    fasta: Path
    fasta_sha256: Sha256
    row_count: Literal[442]
    bootstrap_component_column: Literal["discovery_component_id_cluster30"]


class FrozenTestSplitInput(BaseModel):
    """One exact v0.2 split and its complete content identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FrozenSplitName
    manifest: Path
    file_sha256: Sha256
    semantic_sha256: Sha256
    content_manifest: Path
    content_manifest_sha256: Sha256
    train_count: Literal[308]
    validation_count: Literal[68]
    test_count: Literal[66]


class FrozenTestMethodDefinition(BaseModel):
    """One v0.5 method assembled only from released constituent configs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FrozenMethodName
    feature_config: Path | None = None
    model_config_path: Path = Field(alias="model_config")
    embedding_config: Path | None = None

    @model_validator(mode="after")
    def require_released_constituents(self) -> FrozenTestMethodDefinition:
        """Reject copied, substituted, or tunable method definitions."""

        expected: dict[str, tuple[str | None, str, str | None]] = {
            "majority": (None, "configs/model/majority.yaml", None),
            "length_logistic": (
                "configs/feature/length.yaml",
                "configs/model/logistic_regression.yaml",
                None,
            ),
            "aac_logistic": (
                "configs/feature/aac.yaml",
                "configs/model/logistic_regression.yaml",
                None,
            ),
            "kmer3_logistic": (
                "configs/feature/kmer3.yaml",
                "configs/model/logistic_regression.yaml",
                None,
            ),
            "nearest_homolog": (None, "configs/model/nearest_homolog.yaml", None),
            "esm2_35m": (
                None,
                "configs/model/esm_linear_probe.yaml",
                "configs/embedding/esm2_35m.yaml",
            ),
            "esm2_150m": (
                None,
                "configs/model/esm_linear_probe.yaml",
                "configs/embedding/esm2_150m.yaml",
            ),
        }
        feature, model, embedding = expected[self.name]
        values = (self.feature_config, self.model_config_path, self.embedding_config)
        suffixes = (feature, model, embedding)
        for value, suffix in zip(values, suffixes, strict=True):
            if suffix is None:
                if value is not None:
                    raise ValueError(f"{self.name} has an unapproved constituent config")
            elif value is None or not value.as_posix().endswith(suffix):
                raise ValueError(f"{self.name} must reference {suffix}")
        return self


class FrozenTrackedEvidence(BaseModel):
    """One immutable tracked protocol, config, or released aggregate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    sha256: Sha256


class FrozenModelSnapshotIdentity(BaseModel):
    """Offline ESM snapshot identity without model bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["esm2_35m", "esm2_150m"]
    manifest: Path
    manifest_sha256: Sha256
    repository: Literal["facebook/esm2_t12_35M_UR50D", "facebook/esm2_t30_150M_UR50D"]
    revision: GitRevision
    canonical_snapshot_sha256: Sha256
    tokenizer_sha256: Sha256
    model_weight_sha256: Sha256


class FrozenTestEvaluationConfig(BaseModel):
    """Train-only fitting and delayed Test evaluation policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fit_partition: Literal["train"]
    evaluation_partition: Literal["test"]
    validation_policy: Literal["excluded"]
    label_order: tuple[str, ...]
    zero_division: Literal[0]
    real_test_access_authorized: Literal[False]

    @model_validator(mode="after")
    def require_frozen_label_order(self) -> FrozenTestEvaluationConfig:
        """Keep metric, score, and confusion axes fixed."""

        if self.label_order != ("2.7", "3.1", "1.1", "2.1", "4.1"):
            raise ValueError("v0.5 evaluation must use the frozen five-label order")
        return self


class BootstrapSpec(BaseModel):
    """Maintainer-approved group-aware percentile interval definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    iterations: Literal[2000]
    confidence_level: float
    lower_quantile: float
    upper_quantile: float
    seed: Literal[2026]
    unit: Literal["cluster30_discovery_component"]
    interval_method: Literal["percentile"]
    quantile_method: Literal["linear"]

    @model_validator(mode="after")
    def require_fixed_interval(self) -> BootstrapSpec:
        """Reject any confidence level or percentile-bound change."""

        if (
            self.confidence_level != 0.95
            or self.lower_quantile != 0.025
            or self.upper_quantile != 0.975
        ):
            raise ValueError("v0.5 bootstrap interval values must remain frozen")
        return self


class FrozenMethodComparison(BaseModel):
    """One directed paired comparison frozen before Test access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_a: FrozenMethodName
    method_b: FrozenMethodName


class FrozenTestStatisticsConfig(BaseModel):
    """Exact metric, interval, and comparison families for v0.5."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_metrics: tuple[Literal["macro_f1", "balanced_accuracy"], ...]
    bootstrap: BootstrapSpec
    within_split_resampling: Literal["paired"]
    method_comparisons: tuple[FrozenMethodComparison, ...]
    generalization_metric: Literal["macro_f1"]
    generalization_reference_split: Literal["random"]
    generalization_comparison_splits: tuple[FrozenSplitName, ...]
    cross_split_resampling: Literal["independent"]

    @model_validator(mode="after")
    def require_fixed_statistics(self) -> FrozenTestStatisticsConfig:
        """Reject extra metrics, comparisons, or split contrast families."""

        if self.primary_metrics != ("macro_f1", "balanced_accuracy"):
            raise ValueError("v0.5 primary metrics must remain frozen in order")
        comparisons = tuple((item.method_a, item.method_b) for item in self.method_comparisons)
        if comparisons != (
            ("esm2_35m", "aac_logistic"),
            ("esm2_35m", "kmer3_logistic"),
            ("esm2_150m", "aac_logistic"),
            ("esm2_150m", "kmer3_logistic"),
            ("esm2_150m", "esm2_35m"),
        ):
            raise ValueError("v0.5 method comparisons must remain frozen in order")
        if self.generalization_comparison_splits != ("cluster70", "cluster50", "cluster30"):
            raise ValueError("v0.5 generalization gaps must remain frozen in order")
        return self


class FrozenTestRuntimeConfig(BaseModel):
    """Canonical same-platform formal runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: Literal[42]
    operating_system: Literal["Darwin"]
    architecture: Literal["arm64"]
    device: Literal["cpu"]
    dtype: Literal["float32"]
    torch_intraop_threads: Literal[8]
    torch_interop_threads: Literal[1]
    deterministic_algorithms: Literal[True]
    mmseqs_version: Literal["18-8cc5c"]
    mmseqs_threads: Literal[8]
    local_files_only: Literal[True]
    network_access: Literal[False]


class FrozenTestOutputConfig(BaseModel):
    """Immutable local-only v0.5 run destination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    refuse_overwrite: Literal[True]

    @model_validator(mode="after")
    def require_fixed_root(self) -> FrozenTestOutputConfig:
        """Prevent a config-level output override."""

        if not self.root.as_posix().endswith("results/runs/v0.5.0-test-r1"):
            raise ValueError("outputs.root must be the fixed v0.5 r1 Test run root")
        return self


class FrozenTestExperimentConfig(BaseModel):
    """Exact seven-by-four Test request that carries no authorization itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    experiment_type: Literal["frozen_test"]
    name: Literal["v050-frozen-test"]
    protocol_revision: Literal["r1"]
    cohort: FrozenCohortInput
    splits: tuple[FrozenTestSplitInput, ...]
    methods: tuple[FrozenTestMethodDefinition, ...]
    model_snapshots: tuple[FrozenModelSnapshotIdentity, ...]
    tracked_evidence: tuple[FrozenTrackedEvidence, ...]
    evaluation: FrozenTestEvaluationConfig
    statistics: FrozenTestStatisticsConfig
    runtime: FrozenTestRuntimeConfig
    formal_sessions: tuple[Literal["run-a", "run-b"], ...]
    outputs: FrozenTestOutputConfig
    attestation: Path

    @property
    def cell_count(self) -> int:
        """Return the exact formal Test matrix size."""

        return len(self.methods) * len(self.splits)

    @model_validator(mode="after")
    def require_fixed_matrix(self) -> FrozenTestExperimentConfig:
        """Reject every matrix, session, evidence, or identity substitution."""

        if tuple(item.name for item in self.methods) != (
            "majority",
            "length_logistic",
            "aac_logistic",
            "kmer3_logistic",
            "nearest_homolog",
            "esm2_35m",
            "esm2_150m",
        ):
            raise ValueError("experiment must declare the seven frozen methods in order")
        if tuple(item.name for item in self.splits) != (
            "random",
            "cluster70",
            "cluster50",
            "cluster30",
        ):
            raise ValueError("experiment must declare the four frozen splits in order")
        if self.cell_count != 28:
            raise ValueError("v0.5 experiment must contain exactly 28 cells")
        if self.formal_sessions != ("run-a", "run-b"):
            raise ValueError("v0.5 formal sessions must be exactly run-a then run-b")
        if tuple(item.name for item in self.model_snapshots) != ("esm2_35m", "esm2_150m"):
            raise ValueError("v0.5 model snapshots must remain frozen in order")
        if not self.attestation.as_posix().endswith("docs/attestations/v0.5.0-test-freeze-r1.yaml"):
            raise ValueError("v0.5 r1 requires its future Test-freeze attestation path")
        return self


__all__ = [
    "BootstrapSpec",
    "EsmExperimentConfig",
    "ExperimentConfig",
    "FrozenMethodName",
    "FrozenSplitName",
    "FrozenTestExperimentConfig",
]
