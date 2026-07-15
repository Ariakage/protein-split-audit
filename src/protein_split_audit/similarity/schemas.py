# SPDX-License-Identifier: Apache-2.0

"""Validated configuration schemas for fixed-parameter similarity operations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_fixed_floats(values: tuple[tuple[str, float, float], ...]) -> None:
    """Reject changes to protocol-fixed floating-point values."""

    for field_name, value, expected in values:
        if value != expected:
            raise ValueError(f"{field_name} must be {expected}")


class MmseqsRuntimeConfig(_FrozenConfig):
    """Runtime-only MMseqs2 controls shared by similarity operations."""

    executable: str = Field(min_length=1)
    cache_root: Path
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    threads: int = Field(ge=1)

    @field_validator("executable")
    @classmethod
    def executable_must_not_be_blank(cls, value: str) -> str:
        """Reject executable names containing only whitespace."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("executable must not be blank")
        return stripped


class ClusterParameters(_FrozenConfig):
    """Scientific parameters accepted by MMseqs2 ``easy-cluster``."""

    sensitivity: float
    evalue: float
    sequence_identity_mode: Literal[0]
    min_sequence_identity: float
    minimum_coverage: float
    coverage_mode: Literal[0]
    alignment_mode: Literal[3]
    cluster_mode: Literal[0]
    cluster_reassign: Literal[True]

    @model_validator(mode="after")
    def floats_must_match_protocol(self) -> ClusterParameters:
        """Allow only the three named thresholds and fixed shared values."""

        _require_fixed_floats(
            (
                ("sensitivity", self.sensitivity, 7.5),
                ("evalue", self.evalue, 0.001),
                ("minimum_coverage", self.minimum_coverage, 0.80),
            )
        )
        if self.min_sequence_identity not in {0.30, 0.50, 0.70}:
            raise ValueError("min_sequence_identity must be 0.30, 0.50, or 0.70")
        return self


class SelfSearchParameters(_FrozenConfig):
    """Scientific parameters for the one fixed 30% all-vs-all search."""

    sensitivity: float
    evalue: float
    search_type: Literal[1]
    sequence_identity_mode: Literal[0]
    min_sequence_identity: float
    minimum_coverage: float
    coverage_mode: Literal[0]
    alignment_mode: Literal[3]
    format_mode: Literal[4]

    @model_validator(mode="after")
    def floats_must_match_protocol(self) -> SelfSearchParameters:
        """Keep the discovery search predicate fixed."""

        _require_fixed_floats(
            (
                ("sensitivity", self.sensitivity, 7.5),
                ("evalue", self.evalue, 0.001),
                ("min_sequence_identity", self.min_sequence_identity, 0.30),
                ("minimum_coverage", self.minimum_coverage, 0.80),
            )
        )
        return self


class AuditSearchParameters(_FrozenConfig):
    """Scientific parameters for the independent test-to-train search."""

    sensitivity: float
    evalue: float
    search_type: Literal[1]
    sequence_identity_mode: Literal[0]
    min_sequence_identity: float
    minimum_coverage: float
    coverage_mode: Literal[0]
    alignment_mode: Literal[3]
    format_mode: Literal[4]

    @model_validator(mode="after")
    def floats_must_match_protocol(self) -> AuditSearchParameters:
        """Keep the independent audit search predicate fixed."""

        _require_fixed_floats(
            (
                ("sensitivity", self.sensitivity, 7.5),
                ("evalue", self.evalue, 0.001),
                ("min_sequence_identity", self.min_sequence_identity, 0.0),
                ("minimum_coverage", self.minimum_coverage, 0.80),
            )
        )
        return self


class CandidateDiscoveryInputConfig(_FrozenConfig):
    """Verified candidate-pool inputs for the discovery search."""

    candidate_dataset: Path
    build_manifest: Path
    fasta: Path


class CohortClusterBaseInputConfig(_FrozenConfig):
    """Frozen-cohort inputs for the base 30% cluster/search operation."""

    cohort_manifest: Path
    cohort_content_manifest: Path
    fasta: Path


class CohortClusterDerivedInputConfig(CohortClusterBaseInputConfig):
    """Base-pair inputs required to derive 50% or 70% components."""

    base_pair_table: Path
    base_pair_content_manifest: Path
    base_pair_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AuditInputConfig(_FrozenConfig):
    """Split and cohort inputs for a train-test similarity audit."""

    split_manifest: Path
    split_content_manifest: Path
    cohort_manifest: Path
    cohort_content_manifest: Path
    cohort_fasta: Path


class _DistinctOutputConfig(_FrozenConfig):
    """Shared exact-path collision guard for output models."""

    def _ensure_distinct(self, paths: tuple[Path, ...]) -> None:
        if len(set(paths)) != len(paths):
            raise ValueError("similarity output paths must be distinct")


class CandidateDiscoveryOutputConfig(_DistinctOutputConfig):
    """Destinations produced by candidate-pool discovery."""

    component_manifest: Path
    content_manifest: Path
    pair_table: Path
    run_dir: Path
    overwrite: Literal[False] = False

    @model_validator(mode="after")
    def output_paths_must_be_distinct(self) -> CandidateDiscoveryOutputConfig:
        """Reject exact destination collisions."""

        self._ensure_distinct(
            (self.component_manifest, self.content_manifest, self.pair_table, self.run_dir)
        )
        return self


class CohortClusterBaseOutputConfig(_DistinctOutputConfig):
    """Destinations produced by the base cohort operation."""

    cluster_manifest: Path
    content_manifest: Path
    pair_table: Path
    run_dir: Path
    overwrite: Literal[False] = False

    @model_validator(mode="after")
    def output_paths_must_be_distinct(self) -> CohortClusterBaseOutputConfig:
        """Reject exact destination collisions."""

        self._ensure_distinct(
            (self.cluster_manifest, self.content_manifest, self.pair_table, self.run_dir)
        )
        return self


class CohortClusterDerivedOutputConfig(_DistinctOutputConfig):
    """Destinations produced by a derived cohort operation."""

    cluster_manifest: Path
    content_manifest: Path
    run_dir: Path
    overwrite: Literal[False] = False

    @model_validator(mode="after")
    def output_paths_must_be_distinct(self) -> CohortClusterDerivedOutputConfig:
        """Reject exact destination collisions."""

        self._ensure_distinct((self.cluster_manifest, self.content_manifest, self.run_dir))
        return self


class AuditOutputConfig(_DistinctOutputConfig):
    """Disjoint outputs for one audit strategy."""

    train_fasta: Path
    test_fasta: Path
    audit_manifest: Path
    content_manifest: Path
    summary: Path
    run_dir: Path
    overwrite: Literal[False] = False

    @model_validator(mode="after")
    def output_paths_must_be_distinct(self) -> AuditOutputConfig:
        """Reject exact destination collisions."""

        self._ensure_distinct(
            (
                self.train_fasta,
                self.test_fasta,
                self.audit_manifest,
                self.content_manifest,
                self.summary,
                self.run_dir,
            )
        )
        return self


class _SimilarityConfigBase(_FrozenConfig):
    schema_version: Literal[1]
    operation: str
    name: str
    run_mode: Literal["development", "freeze"]
    runtime: MmseqsRuntimeConfig


class CandidateDiscoveryConfig(_SimilarityConfigBase):
    """One fixed candidate-pool 30% discovery search."""

    operation: Literal["candidate_discovery"]
    name: Literal["candidate-pool-cluster30"]
    self_search: SelfSearchParameters
    input: CandidateDiscoveryInputConfig
    output: CandidateDiscoveryOutputConfig


class CohortClusterBaseConfig(_SimilarityConfigBase):
    """Descriptive cohort clustering plus the one base 30% self-search."""

    operation: Literal["cohort_cluster_base"]
    name: Literal["cluster30"]
    cluster: ClusterParameters
    self_search: SelfSearchParameters
    input: CohortClusterBaseInputConfig
    output: CohortClusterBaseOutputConfig

    @model_validator(mode="after")
    def cluster_threshold_must_be_base_threshold(self) -> CohortClusterBaseConfig:
        """Keep the base cluster operation at the fixed 30% threshold."""

        if self.cluster.min_sequence_identity != 0.30:
            raise ValueError("cluster30 threshold must be 0.30")
        return self


class CohortClusterDerivedConfig(_SimilarityConfigBase):
    """Descriptive 50% or 70% clustering derived from base pair observations."""

    operation: Literal["cohort_cluster_derived"]
    name: Literal["cluster50", "cluster70"]
    cluster: ClusterParameters
    input: CohortClusterDerivedInputConfig
    output: CohortClusterDerivedOutputConfig

    @model_validator(mode="after")
    def cluster_threshold_must_match_name(self) -> CohortClusterDerivedConfig:
        """Prevent a named derived artifact from using another threshold."""

        expected = {"cluster50": 0.50, "cluster70": 0.70}[self.name]
        if self.cluster.min_sequence_identity != expected:
            raise ValueError(f"{self.name} threshold must be {expected:.2f}")
        return self


class AuditConfig(_SimilarityConfigBase):
    """One independent train-test audit configuration."""

    operation: Literal["audit"]
    name: Literal["random", "cluster70", "cluster50", "cluster30"]
    strategy: Literal["random_control", "similarity_component"]
    violation_identity_threshold: float | None
    search: AuditSearchParameters
    input: AuditInputConfig
    output: AuditOutputConfig

    @model_validator(mode="after")
    def violation_policy_must_match_name(self) -> AuditConfig:
        """Bind each audit name to its fixed strategy and violation policy."""

        expected_strategy = "random_control" if self.name == "random" else "similarity_component"
        expected_threshold = {
            "random": None,
            "cluster70": 0.70,
            "cluster50": 0.50,
            "cluster30": 0.30,
        }[self.name]
        if self.strategy != expected_strategy:
            raise ValueError(f"{self.name} audit strategy must be {expected_strategy}")
        if self.violation_identity_threshold != expected_threshold:
            raise ValueError(
                f"{self.name} violation_identity_threshold must be {expected_threshold}"
            )
        return self


class SimilarityParentLineage(_FrozenConfig):
    """One preserved parent artifact identity and generation state."""

    artifact_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_git_commit: str | None
    generation_git_dirty: bool | None


class SimilarityArtifactDigest(_FrozenConfig):
    """Logical location and byte/semantic hashes for one row artifact."""

    logical_path: str
    row_count: int = Field(ge=0)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateDiscoveryArtifactDigests(_FrozenConfig):
    """The two deterministic row artifacts produced by candidate discovery."""

    pair_table: SimilarityArtifactDigest
    component_manifest: SimilarityArtifactDigest


class CandidateDiscoveryCounts(_FrozenConfig):
    """Aggregate-only candidate discovery counts."""

    sequence_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)
    component_count: int = Field(ge=1)
    singleton_count: int = Field(ge=0)
    largest_component_size: int = Field(ge=1)
    per_class_component_counts: dict[str, int]


class CandidateDiscoveryCommand(_FrozenConfig):
    """Sanitized logical MMseqs2 invocation and fixed scientific controls."""

    sanitized_argv: tuple[str, ...]
    mmseqs_version: str
    max_seqs: int = Field(ge=1)
    fixed_parameters: dict[str, str | int | bool]


class CandidateDiscoveryContentManifest(_FrozenConfig):
    """Timestamp-free aggregate manifest for candidate-pool discovery."""

    manifest_schema_version: Literal[1] = 1
    pair_normalization_rule_version: Literal["observed-pair-best-v1"] = "observed-pair-best-v1"
    component_rule_version: Literal["observed-component-sha256-v1"] = "observed-component-sha256-v1"
    operation: Literal["candidate_discovery"]
    name: Literal["candidate-pool-cluster30"]
    run_mode: Literal["development", "freeze"]
    configuration_file: str
    source_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_lineage: tuple[SimilarityParentLineage, ...]
    candidate_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fasta_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    command: CandidateDiscoveryCommand
    counts: CandidateDiscoveryCounts
    artifacts: CandidateDiscoveryArtifactDigests
    software_version: str
    generation_git_commit: str | None
    generation_git_dirty: bool | None
    python_version: str
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_eligible: bool
    ineligibility_reasons: tuple[str, ...]


class CandidateDiscoveryRunProvenance(_FrozenConfig):
    """Local timestamped execution details excluded from deterministic manifests."""

    run_schema_version: Literal[1] = 1
    started_at_utc: str
    ended_at_utc: str
    resolved_executable: str
    staging_dir: str
    architecture: str
    logical_cpu_count: int | None
    configured_threads: int = Field(ge=1)
    sanitized_argv: tuple[str, ...]
    returncode: int
    timed_out: bool
    stderr_tail: str
    staged_file_sha256: dict[str, str]
    cleanup_succeeded: bool


class CandidateDiscoveryFailureProvenance(_FrozenConfig):
    """Bounded local failure evidence retained only inside a unique staging child."""

    failure_schema_version: Literal[1] = 1
    outcome: Literal["failure"] = "failure"
    started_at_utc: str
    ended_at_utc: str
    failure_stage: str
    failure_reason: str = Field(max_length=512)
    resolved_executable: str | None
    mmseqs_version: str | None
    staging_dir: str
    architecture: str
    logical_cpu_count: int | None
    configured_threads: int = Field(ge=1)
    sanitized_argv: tuple[str, ...]
    returncode: int | None
    timed_out: bool
    stderr_tail: str = Field(max_length=4096)
    runner_cleanup_succeeded: bool | None
    cleanup_succeeded: bool


type SimilarityConfig = Annotated[
    CandidateDiscoveryConfig | CohortClusterBaseConfig | CohortClusterDerivedConfig | AuditConfig,
    Field(discriminator="operation"),
]


__all__ = [
    "AuditConfig",
    "AuditInputConfig",
    "AuditOutputConfig",
    "AuditSearchParameters",
    "CandidateDiscoveryArtifactDigests",
    "CandidateDiscoveryCommand",
    "CandidateDiscoveryConfig",
    "CandidateDiscoveryContentManifest",
    "CandidateDiscoveryCounts",
    "CandidateDiscoveryFailureProvenance",
    "CandidateDiscoveryInputConfig",
    "CandidateDiscoveryOutputConfig",
    "CandidateDiscoveryRunProvenance",
    "ClusterParameters",
    "CohortClusterBaseConfig",
    "CohortClusterBaseInputConfig",
    "CohortClusterBaseOutputConfig",
    "CohortClusterDerivedConfig",
    "CohortClusterDerivedInputConfig",
    "CohortClusterDerivedOutputConfig",
    "MmseqsRuntimeConfig",
    "SelfSearchParameters",
    "SimilarityArtifactDigest",
    "SimilarityConfig",
    "SimilarityParentLineage",
]
