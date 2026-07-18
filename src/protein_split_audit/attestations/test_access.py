# SPDX-License-Identifier: Apache-2.0

"""Strict v0.5 Test authorization, access-budget, and incident boundaries."""

from __future__ import annotations

import json
import os
import platform
import re
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from protein_split_audit import __version__
from protein_split_audit.config import load_embedding_config, load_experiment_config
from protein_split_audit.embeddings.model_registry import verify_model_snapshot
from protein_split_audit.embeddings.provenance import load_snapshot_manifest
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.experiments.test_gate import RealTestAccessDenied
from protein_split_audit.provenance import (
    git_metadata,
    git_output,
    serialize_canonical_json,
    serialize_json_mapping,
    sha256_file,
)
from protein_split_audit.similarity.mmseqs import probe_mmseqs

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
SessionName = Literal["run-a", "run-b"]
_APPROVAL_PATTERN = re.compile(
    r"^https://github\.com/Ariakage/protein-split-audit/"
    r"(?:pull|issues)/[1-9][0-9]*#issuecomment-[1-9][0-9]*$"
)
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_CAPABILITY_TOKEN = object()


class AttestedArtifact(BaseModel):
    """One project-relative immutable file identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    sha256: Sha256


class AttestedCode(BaseModel):
    """Generation A and its versioned environment inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_git_commit: GitCommit
    generation_git_dirty: Literal[False]
    software_version: Literal["0.5.0"]
    python_version: Annotated[str, Field(pattern=r"^3\.12\.[0-9]+$")]
    configuration: AttestedArtifact
    uv_lock: AttestedArtifact
    dependency_diff: AttestedArtifact


class AttestedCohort(BaseModel):
    """Frozen cohort identity copied from the approved v0.5 configuration."""

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


class AttestedSplit(BaseModel):
    """One frozen split identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["random", "cluster70", "cluster50", "cluster30"]
    manifest: Path
    file_sha256: Sha256
    semantic_sha256: Sha256
    content_manifest: Path
    content_manifest_sha256: Sha256
    train_count: Literal[308]
    validation_count: Literal[68]
    test_count: Literal[66]


class AttestedMethod(BaseModel):
    """One method and the released configs that define it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[
        "majority",
        "length_logistic",
        "aac_logistic",
        "kmer3_logistic",
        "nearest_homolog",
        "esm2_35m",
        "esm2_150m",
    ]
    config_paths: tuple[Path, ...] = Field(min_length=1, max_length=2)


class AttestedModelSnapshot(BaseModel):
    """One offline model snapshot identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["esm2_35m", "esm2_150m"]
    manifest: Path
    manifest_sha256: Sha256
    repository: Literal["facebook/esm2_t12_35M_UR50D", "facebook/esm2_t30_150M_UR50D"]
    revision: GitCommit
    canonical_snapshot_sha256: Sha256
    tokenizer_sha256: Sha256
    model_weight_sha256: Sha256


class FrozenAttestationBundle(BaseModel):
    """All immutable data, method, evidence, and snapshot identities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cohort: AttestedCohort
    splits: tuple[AttestedSplit, ...]
    methods: tuple[AttestedMethod, ...]
    tracked_evidence: tuple[AttestedArtifact, ...] = Field(min_length=1)
    model_snapshots: tuple[AttestedModelSnapshot, ...]

    @model_validator(mode="after")
    def require_ordered_identities(self) -> FrozenAttestationBundle:
        """Freeze every ordered identity family."""

        if tuple(item.name for item in self.splits) != (
            "random",
            "cluster70",
            "cluster50",
            "cluster30",
        ):
            raise ValueError("attested splits must remain frozen in order")
        if tuple(item.name for item in self.methods) != (
            "majority",
            "length_logistic",
            "aac_logistic",
            "kmer3_logistic",
            "nearest_homolog",
            "esm2_35m",
            "esm2_150m",
        ):
            raise ValueError("attested methods must remain frozen in order")
        if tuple(item.name for item in self.model_snapshots) != (
            "esm2_35m",
            "esm2_150m",
        ):
            raise ValueError("attested model snapshots must remain frozen in order")
        return self


class AttestedExperiment(BaseModel):
    """Exact 28-cell access grant and nothing wider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    methods: tuple[str, ...]
    splits: tuple[str, ...]
    matrix_cells: Literal[28]
    fit_partition: Literal["train"]
    evaluation_partition: Literal["test"]
    validation_policy: Literal["excluded"]
    formal_sessions: tuple[SessionName, ...]
    real_test_access_authorized: Literal[True]

    @model_validator(mode="after")
    def require_exact_matrix(self) -> AttestedExperiment:
        """Reject partial, reordered, or expanded authority."""

        if self.methods != (
            "majority",
            "length_logistic",
            "aac_logistic",
            "kmer3_logistic",
            "nearest_homolog",
            "esm2_35m",
            "esm2_150m",
        ):
            raise ValueError("attested methods must remain frozen in order")
        if self.splits != ("random", "cluster70", "cluster50", "cluster30"):
            raise ValueError("attested splits must remain frozen in order")
        if self.formal_sessions != ("run-a", "run-b"):
            raise ValueError("formal sessions must be exactly run-a then run-b")
        return self


class AttestedBootstrap(BaseModel):
    """Approved v0.5 group-bootstrap identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: Literal["cluster30_discovery_component"]
    iterations: Literal[2000]
    confidence_level: float
    interval_method: Literal["percentile"]
    lower_quantile: float
    upper_quantile: float
    seed: Literal[2026]

    @model_validator(mode="after")
    def require_interval_values(self) -> AttestedBootstrap:
        """Keep percentile bounds fixed."""

        if (
            self.confidence_level != 0.95
            or self.lower_quantile != 0.025
            or self.upper_quantile != 0.975
        ):
            raise ValueError("attested percentile interval must remain frozen")
        return self


class AttestedStatistics(BaseModel):
    """Approved paired and independent resampling policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bootstrap: AttestedBootstrap
    within_split_resampling: Literal["paired"]
    cross_split_resampling: Literal["independent"]


class AttestedDependencyVersions(BaseModel):
    """Exact formal third-party runtime versions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    torch: Literal["2.13.0"]
    transformers: Literal["5.13.1"]
    safetensors: Literal["0.8.0"]
    tokenizers: Literal["0.22.2"]
    huggingface_hub: Literal["1.23.0"]
    accelerate: Literal["1.14.0"]


class AttestedRuntime(BaseModel):
    """Canonical formal platform and dependency identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operating_system: Literal["Darwin"]
    architecture: Literal["arm64"]
    python_version: Annotated[str, Field(pattern=r"^3\.12\.[0-9]+$")]
    device: Literal["cpu"]
    dtype: Literal["float32"]
    torch_intraop_threads: Literal[8]
    torch_interop_threads: Literal[1]
    deterministic_algorithms: Literal[True]
    mmseqs_version: Literal["18-8cc5c"]
    mmseqs_threads: Literal[8]
    local_files_only: Literal[True]
    network_access: Literal[False]
    dependency_versions: AttestedDependencyVersions


class AttestedApproval(BaseModel):
    """Permanent owner-authored Test authorization evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved_by: Literal["Ariakage"]
    approved_at_utc: datetime
    approval_reference: str
    author_association: Literal["OWNER"]
    approval_comment_sha256: Sha256

    @field_validator("approval_reference")
    @classmethod
    def reference_must_be_permanent_github_comment(cls, value: str) -> str:
        """Accept only a permanent comment in the project repository."""

        if _APPROVAL_PATTERN.fullmatch(value) is None:
            raise ValueError("approval_reference must be a permanent GitHub PR/Issue comment")
        return value

    @field_validator("approved_at_utc")
    @classmethod
    def approval_time_must_be_utc(cls, value: datetime) -> datetime:
        """Reject naive or non-UTC approval timestamps."""

        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("approved_at_utc must be timezone-aware UTC")
        return value


class TestFreezeAttestation(BaseModel):
    """Complete, strict machine-readable v0.5 Test authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    project: Literal["ProteinSplitAudit"]
    release_target: Literal["v0.5.0"]
    attestation_type: Literal["frozen_test_access"]
    protocol: AttestedArtifact
    code: AttestedCode
    frozen: FrozenAttestationBundle
    experiment: AttestedExperiment
    statistics: AttestedStatistics
    runtime: AttestedRuntime
    approval: AttestedApproval


@dataclass(frozen=True, slots=True)
class FormalRuntimeIdentity:
    """Observed runtime values supplied to the formal gate."""

    software_version: str
    python_version: str
    operating_system: str
    architecture: str
    device: str
    dtype: str
    torch_intraop_threads: int
    torch_interop_threads: int
    deterministic_algorithms: bool
    mmseqs_version: str
    mmseqs_threads: int
    local_files_only: bool
    network_access: bool
    dependency_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        """Detach and freeze the dependency mapping."""

        object.__setattr__(
            self,
            "dependency_versions",
            MappingProxyType(dict(self.dependency_versions)),
        )


@dataclass(frozen=True, slots=True)
class VerifiedTestAuthorization:
    """Opaque capability returned only by the complete v0.5 gate."""

    attestation_path: Path
    attestation_sha256: str
    generation_commit: str
    execution_commit: str
    approval_reference: str
    allowed_sessions: tuple[SessionName, ...]
    protocol_sha256: str
    config_sha256: str
    lock_sha256: str
    dependency_diff_sha256: str
    frozen_hashes: Mapping[str, str]
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """Detach and freeze the verified hash inventory."""

        object.__setattr__(self, "frozen_hashes", MappingProxyType(dict(self.frozen_hashes)))


def collect_formal_runtime_identity() -> FormalRuntimeIdentity:
    """Probe the canonical local runtime without network access."""

    dependencies = {
        key: version(distribution)
        for key, distribution in (
            ("torch", "torch"),
            ("transformers", "transformers"),
            ("safetensors", "safetensors"),
            ("tokenizers", "tokenizers"),
            ("huggingface_hub", "huggingface-hub"),
            ("accelerate", "accelerate"),
        )
    }
    tool = probe_mmseqs("mmseqs")
    return FormalRuntimeIdentity(
        software_version=__version__,
        python_version=platform.python_version(),
        operating_system=platform.system(),
        architecture=platform.machine(),
        device="cpu",
        dtype="float32",
        torch_intraop_threads=8,
        torch_interop_threads=1,
        deterministic_algorithms=True,
        mmseqs_version=tool.version,
        mmseqs_threads=8,
        local_files_only=True,
        network_access=False,
        dependency_versions=dependencies,
    )


def _resolve_attested_path(root: Path, value: Path) -> Path:
    if value.is_absolute():
        raise ValueError("attested paths must be project-relative")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("attested paths must remain inside the project root")
    return resolved


def _logical_path(root: Path, value: Path) -> str:
    return value.resolve().relative_to(root).as_posix()


def _method_identity(
    config: FrozenTestExperimentConfig,
    root: Path,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            method.name,
            tuple(
                _logical_path(root, path)
                for path in (
                    method.feature_config,
                    method.model_config_path,
                    method.embedding_config,
                )
                if path is not None
            ),
        )
        for method in config.methods
    )


def _attested_method_identity(
    attestation: TestFreezeAttestation,
    root: Path,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            method.name,
            tuple(
                _logical_path(root, _resolve_attested_path(root, path))
                for path in method.config_paths
            ),
        )
        for method in attestation.frozen.methods
    )


def _verify_config_binding(
    config: FrozenTestExperimentConfig,
    attestation: TestFreezeAttestation,
    config_path: Path,
    root: Path,
    runtime: FormalRuntimeIdentity,
) -> None:
    """Compare all non-row attestation values before frozen files are touched."""

    expected_static = {
        "configuration": ("configs/experiment/v050-test.yaml", config_path),
        "protocol": (
            "docs/protocols/v0.5.0-frozen-test-evaluation.md",
            root / "docs/protocols/v0.5.0-frozen-test-evaluation.md",
        ),
        "uv_lock": ("uv.lock", root / "uv.lock"),
        "dependency_diff": (
            "docs/audits/v0.5.0-dependency-diff.md",
            root / "docs/audits/v0.5.0-dependency-diff.md",
        ),
    }
    artifacts = {
        "configuration": attestation.code.configuration,
        "protocol": attestation.protocol,
        "uv_lock": attestation.code.uv_lock,
        "dependency_diff": attestation.code.dependency_diff,
    }
    for name, (logical, physical) in expected_static.items():
        artifact = artifacts[name]
        if artifact.path.as_posix() != logical or artifact.sha256 != sha256_file(physical):
            raise ValueError(f"attested {name} identity mismatch")

    cohort = attestation.frozen.cohort
    if (
        _resolve_attested_path(root, cohort.manifest) != config.cohort.manifest
        or cohort.file_sha256 != config.cohort.file_sha256
        or cohort.semantic_sha256 != config.cohort.semantic_sha256
        or _resolve_attested_path(root, cohort.content_manifest) != config.cohort.content_manifest
        or cohort.content_manifest_sha256 != config.cohort.content_manifest_sha256
        or _resolve_attested_path(root, cohort.fasta) != config.cohort.fasta
        or cohort.fasta_sha256 != config.cohort.fasta_sha256
        or cohort.row_count != config.cohort.row_count
        or cohort.bootstrap_component_column != config.cohort.bootstrap_component_column
    ):
        raise ValueError("attested cohort identity mismatch")

    split_values = tuple(
        (
            item.name,
            _resolve_attested_path(root, item.manifest),
            item.file_sha256,
            item.semantic_sha256,
            _resolve_attested_path(root, item.content_manifest),
            item.content_manifest_sha256,
            item.train_count,
            item.validation_count,
            item.test_count,
        )
        for item in attestation.frozen.splits
    )
    config_splits = tuple(
        (
            item.name,
            item.manifest,
            item.file_sha256,
            item.semantic_sha256,
            item.content_manifest,
            item.content_manifest_sha256,
            item.train_count,
            item.validation_count,
            item.test_count,
        )
        for item in config.splits
    )
    if split_values != config_splits:
        raise ValueError("attested split identities mismatch")
    if _attested_method_identity(attestation, root) != _method_identity(config, root):
        raise ValueError("attested method identities mismatch")

    evidence = tuple(
        (_resolve_attested_path(root, item.path), item.sha256)
        for item in attestation.frozen.tracked_evidence
    )
    if evidence != tuple((item.path, item.sha256) for item in config.tracked_evidence):
        raise ValueError("attested tracked evidence mismatch")
    snapshots = tuple(
        (
            item.name,
            _resolve_attested_path(root, item.manifest),
            item.manifest_sha256,
            item.repository,
            item.revision,
            item.canonical_snapshot_sha256,
            item.tokenizer_sha256,
            item.model_weight_sha256,
        )
        for item in attestation.frozen.model_snapshots
    )
    config_snapshots = tuple(
        (
            item.name,
            item.manifest,
            item.manifest_sha256,
            item.repository,
            item.revision,
            item.canonical_snapshot_sha256,
            item.tokenizer_sha256,
            item.model_weight_sha256,
        )
        for item in config.model_snapshots
    )
    if snapshots != config_snapshots:
        raise ValueError("attested model snapshot identities mismatch")

    if (
        attestation.experiment.methods != tuple(item.name for item in config.methods)
        or attestation.experiment.splits != tuple(item.name for item in config.splits)
        or attestation.experiment.matrix_cells != config.cell_count
        or attestation.experiment.formal_sessions != config.formal_sessions
    ):
        raise ValueError("attested experiment matrix mismatch")
    bootstrap = attestation.statistics.bootstrap
    configured_bootstrap = config.statistics.bootstrap
    if (
        bootstrap.unit != configured_bootstrap.unit
        or bootstrap.iterations != configured_bootstrap.iterations
        or bootstrap.confidence_level != configured_bootstrap.confidence_level
        or bootstrap.interval_method != configured_bootstrap.interval_method
        or bootstrap.lower_quantile != configured_bootstrap.lower_quantile
        or bootstrap.upper_quantile != configured_bootstrap.upper_quantile
        or bootstrap.seed != configured_bootstrap.seed
        or attestation.statistics.within_split_resampling
        != config.statistics.within_split_resampling
        or attestation.statistics.cross_split_resampling != config.statistics.cross_split_resampling
    ):
        raise ValueError("attested statistics mismatch")

    observed_runtime = {
        "operating_system": runtime.operating_system,
        "architecture": runtime.architecture,
        "python_version": runtime.python_version,
        "device": runtime.device,
        "dtype": runtime.dtype,
        "torch_intraop_threads": runtime.torch_intraop_threads,
        "torch_interop_threads": runtime.torch_interop_threads,
        "deterministic_algorithms": runtime.deterministic_algorithms,
        "mmseqs_version": runtime.mmseqs_version,
        "mmseqs_threads": runtime.mmseqs_threads,
        "local_files_only": runtime.local_files_only,
        "network_access": runtime.network_access,
        "dependency_versions": dict(runtime.dependency_versions),
    }
    if attestation.runtime.model_dump(mode="python") != observed_runtime:
        raise ValueError("attested formal runtime mismatch")
    if (
        runtime.software_version != attestation.code.software_version
        or runtime.python_version != attestation.code.python_version
    ):
        raise ValueError("attested software identity mismatch")


def _verify_git_binding(
    root: Path,
    attestation_path: Path,
    attestation: TestFreezeAttestation,
) -> str:
    """Require clean B, sole parent A, and an attestation-only A-to-B diff."""

    git = git_metadata(root)
    if not git.available or git.commit is None or git.dirty is not False:
        raise ValueError("formal Test authorization requires a clean Git worktree")
    relative = attestation_path.relative_to(root).as_posix()
    execution = git_output(
        root,
        "log",
        "--diff-filter=A",
        "-1",
        "--format=%H",
        "--",
        relative,
    )
    if re.fullmatch(r"[0-9a-f]{40}", execution) is None or execution != git.commit:
        raise ValueError("HEAD must be the commit that introduced the Test attestation")
    parents = git_output(root, "rev-list", "--parents", "-n", "1", execution).split()
    if len(parents) != 2 or parents[1] != attestation.code.generation_git_commit:
        raise ValueError("Attestation B must have Generation A as its sole parent")
    changed = tuple(
        line
        for line in git_output(
            root,
            "diff",
            "--name-only",
            attestation.code.generation_git_commit,
            execution,
        ).splitlines()
        if line
    )
    if changed != (relative,):
        raise ValueError("A-to-B tracked diff must contain only the Test attestation")
    return execution


def _verify_frozen_files(
    config: FrozenTestExperimentConfig,
    hasher: Callable[[Path], str],
) -> dict[str, str]:
    """Hash every approved frozen file only after metadata and Git gates pass."""

    expected: dict[Path, str] = {
        config.cohort.manifest: config.cohort.file_sha256,
        config.cohort.content_manifest: config.cohort.content_manifest_sha256,
        config.cohort.fasta: config.cohort.fasta_sha256,
    }
    for split in config.splits:
        expected[split.manifest] = split.file_sha256
        expected[split.content_manifest] = split.content_manifest_sha256
    for evidence in config.tracked_evidence:
        expected[evidence.path] = evidence.sha256
    for snapshot in config.model_snapshots:
        expected[snapshot.manifest] = snapshot.manifest_sha256

    method_paths = {
        path
        for method in config.methods
        for path in (method.feature_config, method.model_config_path, method.embedding_config)
        if path is not None
    }
    if not method_paths.issubset(expected):
        raise ValueError("method configuration is missing from tracked evidence")

    verified: dict[str, str] = {}
    for path, digest in sorted(expected.items(), key=lambda item: item[0].as_posix()):
        observed = hasher(path)
        if observed != digest:
            raise ValueError(f"frozen file hash mismatch: {path.name}")
        verified[path.as_posix()] = observed
    return verified


def _verify_local_model_snapshots(config: FrozenTestExperimentConfig) -> None:
    """Recompute both approved five-file snapshot identities offline."""

    embedding_paths = {
        method.name: method.embedding_config
        for method in config.methods
        if method.embedding_config is not None
    }
    for identity in config.model_snapshots:
        embedding_path = embedding_paths.get(identity.name)
        if embedding_path is None:
            raise ValueError("model snapshot has no frozen embedding configuration")
        embedding = load_embedding_config(embedding_path)
        manifest = load_snapshot_manifest(identity.manifest)
        if (
            manifest.model_id != identity.name
            or manifest.repository != identity.repository
            or manifest.revision != identity.revision
            or manifest.snapshot_sha256 != identity.canonical_snapshot_sha256
            or manifest.tokenizer_sha256 != identity.tokenizer_sha256
            or manifest.model_weight_sha256 != identity.model_weight_sha256
        ):
            raise ValueError("model snapshot manifest identity mismatch")
        verify_model_snapshot(embedding, manifest)


def _verify_test_authorization(
    config_path: Path,
    project_root: Path,
    *,
    runtime: FormalRuntimeIdentity | None,
    frozen_file_hasher: Callable[[Path], str],
    snapshot_verifier: Callable[[FrozenTestExperimentConfig], None],
) -> VerifiedTestAuthorization:
    root = project_root.resolve()
    resolved_config = config_path.resolve()
    if not resolved_config.is_relative_to(root):
        raise ValueError("v0.5 configuration must be inside the project root")
    config = load_experiment_config(resolved_config)
    if not isinstance(config, FrozenTestExperimentConfig):
        raise ValueError("only frozen_test configuration can request Test authorization")
    attestation_path = config.attestation
    try:
        loaded = yaml.safe_load(attestation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError("v0.5 Test attestation is absent or malformed") from error
    attestation = TestFreezeAttestation.model_validate(loaded)
    observed_runtime = runtime if runtime is not None else collect_formal_runtime_identity()

    _verify_config_binding(config, attestation, resolved_config, root, observed_runtime)
    execution = _verify_git_binding(root, attestation_path, attestation)
    if config.outputs.root.exists():
        raise ValueError("formal Test output root must not exist before execution")
    verified = _verify_frozen_files(config, frozen_file_hasher)
    snapshot_verifier(config)
    return VerifiedTestAuthorization(
        attestation_path=attestation_path,
        attestation_sha256=sha256_file(attestation_path),
        generation_commit=attestation.code.generation_git_commit,
        execution_commit=execution,
        approval_reference=attestation.approval.approval_reference,
        allowed_sessions=attestation.experiment.formal_sessions,
        protocol_sha256=attestation.protocol.sha256,
        config_sha256=attestation.code.configuration.sha256,
        lock_sha256=attestation.code.uv_lock.sha256,
        dependency_diff_sha256=attestation.code.dependency_diff.sha256,
        frozen_hashes=verified,
        _token=_CAPABILITY_TOKEN,
    )


def verify_test_authorization(
    config_path: Path,
    project_root: Path,
    *,
    runtime: FormalRuntimeIdentity | None = None,
    frozen_file_hasher: Callable[[Path], str] = sha256_file,
    snapshot_verifier: Callable[[FrozenTestExperimentConfig], None] = _verify_local_model_snapshots,
) -> VerifiedTestAuthorization:
    """Return authority only after every frozen value verifies, otherwise deny uniformly."""

    try:
        return _verify_test_authorization(
            config_path,
            project_root,
            runtime=runtime,
            frozen_file_hasher=frozen_file_hasher,
            snapshot_verifier=snapshot_verifier,
        )
    except RealTestAccessDenied:
        raise
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        raise RealTestAccessDenied(
            "Real test access is not authorized by the active v0.5 attestation"
        ) from error


def require_verified_authorization(authorization: VerifiedTestAuthorization) -> None:
    """Reject manually constructed or otherwise invalid capability objects."""

    if (
        not isinstance(authorization, VerifiedTestAuthorization)
        or authorization._token is not _CAPABILITY_TOKEN
    ):
        raise RealTestAccessDenied(
            "Real test access is not authorized by the active v0.5 attestation"
        )


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("access time must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        raise


def begin_test_session(
    authorization: VerifiedTestAuthorization,
    session: SessionName,
    ledger_root: Path,
    *,
    before_test_read: Callable[[], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Path:
    """Atomically consume one session immediately before its first Test read."""

    require_verified_authorization(authorization)
    if session not in authorization.allowed_sessions:
        raise RealTestAccessDenied("Test session is not authorized")
    marker = ledger_root / f"{session}.jsonl"
    event = {
        "attestation_sha256": authorization.attestation_sha256,
        "config_sha256": authorization.config_sha256,
        "event": "test_access_started",
        "execution_commit": authorization.execution_commit,
        "generation_commit": authorization.generation_commit,
        "protocol_sha256": authorization.protocol_sha256,
        "session_id": session,
        "test_access_started_at_utc": _utc_text(now()),
        "test_session_status": "consumed",
    }
    try:
        _write_exclusive(marker, serialize_canonical_json(event))
    except FileExistsError as error:
        raise RealTestAccessDenied(f"Test session {session} is already consumed") from error
    before_test_read()
    return marker


def complete_test_session(
    authorization: VerifiedTestAuthorization,
    session: SessionName,
    ledger_root: Path,
    result_sha256: str,
) -> Path:
    """Append completion without erasing the preceding consumption event."""

    require_verified_authorization(authorization)
    if re.fullmatch(r"[0-9a-f]{64}", result_sha256) is None:
        raise ValueError("result_sha256 must be a lowercase SHA-256 digest")
    marker = ledger_root / f"{session}.jsonl"
    lines = marker.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RealTestAccessDenied("Test session has no consumption event")
    events = [json.loads(line) for line in lines]
    if (
        events[0].get("event") != "test_access_started"
        or events[0].get("execution_commit") != authorization.execution_commit
        or any(item.get("event") == "session_completed" for item in events)
    ):
        raise RealTestAccessDenied("Test session ledger is inconsistent")
    payload = serialize_canonical_json(
        {
            "event": "session_completed",
            "result_sha256": result_sha256,
            "session_id": session,
            "test_session_status": "completed",
        }
    )
    with marker.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return marker


def write_test_incident(
    authorization: VerifiedTestAuthorization,
    session: SessionName,
    incident_root: Path,
    *,
    failure_stage: str,
    exception_class: str,
    partial_results_viewed: bool,
    last_verified_hashes: Mapping[str, str],
    test_access_started_at_utc: str,
) -> Path:
    """Seal one sequence-free local incident without overwriting prior evidence."""

    require_verified_authorization(authorization)
    if session not in authorization.allowed_sessions:
        raise ValueError("incident session is not authorized")
    if _SAFE_NAME_PATTERN.fullmatch(failure_stage) is None:
        raise ValueError("failure_stage is not sanitized")
    if _SAFE_NAME_PATTERN.fullmatch(exception_class) is None:
        raise ValueError("exception_class is not sanitized")
    hashes = dict(sorted(last_verified_hashes.items()))
    if any(
        _SAFE_NAME_PATTERN.fullmatch(name) is None or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for name, digest in hashes.items()
    ):
        raise ValueError("incident hashes are invalid")
    payload: dict[str, object] = {
        "attestation_sha256": authorization.attestation_sha256,
        "exception_class": exception_class,
        "execution_commit": authorization.execution_commit,
        "failure_stage": failure_stage,
        "last_verified_hashes": hashes,
        "partial_results_viewed": partial_results_viewed,
        "session_id": session,
        "test_access_started_at_utc": test_access_started_at_utc,
        "test_session_status": "consumed_failed",
    }
    path = incident_root / f"{session}.incident.json"
    _write_exclusive(path, serialize_json_mapping(payload))
    return path


__all__ = [
    "FormalRuntimeIdentity",
    "RealTestAccessDenied",
    "TestFreezeAttestation",
    "VerifiedTestAuthorization",
    "begin_test_session",
    "collect_formal_runtime_identity",
    "complete_test_session",
    "require_verified_authorization",
    "verify_test_authorization",
    "write_test_incident",
]
