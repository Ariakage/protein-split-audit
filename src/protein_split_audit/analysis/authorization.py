# SPDX-License-Identifier: Apache-2.0

"""Fail-closed authority for analysis of frozen v0.5 Test outputs."""

from __future__ import annotations

import json
import platform
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from protein_split_audit import __version__
from protein_split_audit.analysis.schemas import (
    FORMAL_SESSION_PAIRS,
    LABEL_ORDER,
    METHODS,
    PUBLIC_ARTIFACTS,
    SPLITS,
    AnalysisComparisons,
    AnalysisStatistics,
    AnalysisStrata,
    ArtifactIdentity,
    GitCommit,
    PostTestAnalysisConfig,
    PrivacyThresholds,
    ReportingThresholds,
    Sha256,
)
from protein_split_audit.config import load_analysis_config
from protein_split_audit.provenance import (
    git_metadata,
    git_output,
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)

_APPROVAL_PATTERN = re.compile(
    r"^https://github\.com/Ariakage/protein-split-audit/"
    r"(?:pull|issues)/[1-9][0-9]*#issuecomment-[1-9][0-9]*$"
)
_CAPABILITY_TOKEN = object()


class AnalysisOutputAccessDenied(RuntimeError):
    """Raised when frozen Test-output analysis lacks complete authority."""


class AttestedAnalysisCode(BaseModel):
    """Generation A and the files that define its behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_git_commit: GitCommit
    generation_git_dirty: Literal[False]
    software_version: Literal["0.6.0"]
    python_version: str
    configuration: ArtifactIdentity
    uv_lock: ArtifactIdentity
    dependency_diff: ArtifactIdentity

    @field_validator("python_version")
    @classmethod
    def require_python_312_patch(cls, value: str) -> str:
        if re.fullmatch(r"3\.12\.[0-9]+", value) is None:
            raise ValueError("formal analysis requires a Python 3.12 patch version")
        return value


class AttestedSplitHashes(BaseModel):
    """Exact frozen split file hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    random: Sha256
    cluster70: Sha256
    cluster50: Sha256
    cluster30: Sha256


class AttestedFrozenInputs(BaseModel):
    """All v0.5 identities needed before row-level parsing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    v050_attestation_sha256: Sha256
    v050_replay_sha256: Sha256
    run_a_directory_sha256: Sha256
    run_b_directory_sha256: Sha256
    prediction_inventory_sha256: Sha256
    nearest_homolog_inventory_sha256: Sha256
    combined_analysis_inventory_sha256: Sha256
    cohort_file_sha256: Sha256
    split_file_sha256: AttestedSplitHashes
    canonical_prediction_session: Literal["run-a"]
    replay_evidence_session: Literal["run-b"]


class AttestedAnalysisPermissions(BaseModel):
    """Narrow permission to analyze outputs without any new inference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    new_test_inference_authorized: Literal[False]
    frozen_test_output_analysis_authorized: Literal[True]


class AttestedAnalysisDefinition(BaseModel):
    """Exact method, split, and analysis-session family."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    methods: tuple[str, ...]
    splits: tuple[str, ...]
    label_order: tuple[str, ...]
    formal_sessions: tuple[str, ...]

    @model_validator(mode="after")
    def require_fixed_definition(self) -> AttestedAnalysisDefinition:
        if self.methods != METHODS:
            raise ValueError("attested methods must remain frozen in order")
        if self.splits != SPLITS:
            raise ValueError("attested splits must remain frozen in order")
        if self.label_order != LABEL_ORDER:
            raise ValueError("attested label order must remain frozen")
        if self.formal_sessions not in FORMAL_SESSION_PAIRS:
            raise ValueError("formal sessions must be an approved complete session pair")
        return self


class AttestedAnalysisRuntime(BaseModel):
    """Canonical execution platform with forbidden model and network paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operating_system: Literal["Darwin"]
    architecture: Literal["arm64"]
    python: Literal["3.12"]
    device: Literal["cpu"]
    network_access: Literal[False]
    model_execution: Literal[False]


class AttestedAnalysisPublication(BaseModel):
    """Exact public bundle and no-clobber policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    public_artifacts: tuple[str, ...]
    refuse_overwrite: Literal[True]

    @field_validator("public_artifacts")
    @classmethod
    def require_exact_allowlist(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != PUBLIC_ARTIFACTS:
            raise ValueError("attested public allowlist must contain exactly 19 frozen files")
        return value


class AttestedAnalysisApproval(BaseModel):
    """Permanent owner-authored approval evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved_by: Literal["Ariakage"]
    approved_at_utc: datetime
    approval_reference: str
    author_association: Literal["OWNER"]
    approval_comment_sha256: Sha256

    @field_validator("approval_reference")
    @classmethod
    def require_permanent_reference(cls, value: str) -> str:
        if _APPROVAL_PATTERN.fullmatch(value) is None:
            raise ValueError("approval_reference must be a permanent GitHub PR/Issue comment")
        return value

    @field_validator("approved_at_utc")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("approved_at_utc must be timezone-aware UTC")
        return value


class AnalysisFreezeAttestation(BaseModel):
    """Complete machine-readable authority for frozen-output analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    project: Literal["ProteinSplitAudit"]
    release_target: Literal["v0.6.0"]
    attestation_type: Literal["frozen_test_output_analysis"]
    protocol: ArtifactIdentity
    code: AttestedAnalysisCode
    frozen_inputs: AttestedFrozenInputs
    permissions: AttestedAnalysisPermissions
    analysis: AttestedAnalysisDefinition
    strata: AnalysisStrata
    comparisons: AnalysisComparisons
    statistics: AnalysisStatistics
    reporting: ReportingThresholds
    privacy: PrivacyThresholds
    publication: AttestedAnalysisPublication
    runtime: AttestedAnalysisRuntime
    approval: AttestedAnalysisApproval


@dataclass(frozen=True, slots=True)
class VerifiedAnalysisAuthorization:
    """Opaque capability issued only after every pre-row gate succeeds."""

    attestation_path: Path
    attestation_sha256: str
    generation_commit: str
    execution_commit: str
    approval_reference: str
    canonical_prediction_session: Literal["run-a"]
    replay_evidence_session: Literal["run-b"]
    formal_sessions: tuple[str, ...]
    protocol_sha256: str
    config_sha256: str
    lock_sha256: str
    frozen_hashes: Mapping[str, str]
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "frozen_hashes", MappingProxyType(dict(self.frozen_hashes)))


def _resolve_attested_path(root: Path, value: Path) -> Path:
    if value.is_absolute():
        raise ValueError("attested paths must be project-relative")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("attested paths must remain inside the project root")
    return resolved


def _verify_git_binding(
    root: Path,
    attestation_path: Path,
    attestation: AnalysisFreezeAttestation,
) -> str:
    git = git_metadata(root)
    if not git.available or git.commit is None or git.dirty is not False:
        raise ValueError("formal analysis authorization requires a clean Git worktree")
    relative = attestation_path.relative_to(root).as_posix()
    execution = git_output(root, "log", "--diff-filter=A", "-1", "--format=%H", "--", relative)
    if execution != git.commit or re.fullmatch(r"[0-9a-f]{40}", execution) is None:
        raise ValueError("HEAD must be the commit that introduced the analysis attestation")
    parents = git_output(root, "rev-list", "--parents", "-n", "1", execution).split()
    if len(parents) != 2 or parents[1] != attestation.code.generation_git_commit:
        raise ValueError("Attestation B must have Generation A as its sole parent")
    changed = tuple(
        item
        for item in git_output(
            root,
            "diff",
            "--name-only",
            attestation.code.generation_git_commit,
            execution,
        ).splitlines()
        if item
    )
    if changed != (relative,):
        raise ValueError("A-to-B tracked diff must contain only the analysis attestation")
    return execution


def _directory_sha256(root: Path) -> str:
    if not root.is_dir():
        raise ValueError("frozen input directory is missing")
    inventory = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return sha256_bytes(serialize_canonical_json(inventory))


def _historical_lock_sha256(root: Path) -> str:
    result = subprocess.run(
        ["git", "show", "v0.5.0:uv.lock"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return sha256_bytes(result.stdout)


def verify_frozen_input_hashes(config: PostTestAnalysisConfig) -> None:
    """Authenticate every approved input byte without parsing row-level content."""

    inputs = config.inputs
    simple_files = (
        (inputs.v050_attestation.path, inputs.v050_attestation.sha256),
        (inputs.v050_protocol.path, inputs.v050_protocol.sha256),
        (inputs.v050_config.path, inputs.v050_config.sha256),
        (inputs.run_a.access_ledger.path, inputs.run_a.access_ledger.sha256),
        (inputs.run_a.matrix_summary.path, inputs.run_a.matrix_summary.sha256),
        (inputs.run_a.statistics.path, inputs.run_a.statistics.sha256),
        (inputs.run_b.access_ledger.path, inputs.run_b.access_ledger.sha256),
        (inputs.run_b.matrix_summary.path, inputs.run_b.matrix_summary.sha256),
        (inputs.run_b.statistics.path, inputs.run_b.statistics.sha256),
        (inputs.replay_report.path, inputs.replay_report.sha256),
        (inputs.cohort.manifest, inputs.cohort.file_sha256),
        (inputs.cohort.content_manifest, inputs.cohort.content_manifest_sha256),
        *((item.manifest, item.file_sha256) for item in inputs.splits),
        *((item.content_manifest, item.content_manifest_sha256) for item in inputs.splits),
    )
    for path, expected in simple_files:
        if sha256_file(path) != expected:
            raise ValueError(f"frozen input hash mismatch: {path.name}")
    project_root = inputs.v050_attestation.path.parents[2]
    if _historical_lock_sha256(project_root) != inputs.v050_lock.sha256:
        raise ValueError("released v0.5 lock hash mismatch")
    if _directory_sha256(inputs.run_a.root) != inputs.run_a.directory_sha256:
        raise ValueError("v0.5 Run A directory inventory mismatch")
    if _directory_sha256(inputs.run_b.root) != inputs.run_b.directory_sha256:
        raise ValueError("v0.5 Run B directory inventory mismatch")
    if (
        _directory_sha256(inputs.reviewed_aggregate.root)
        != inputs.reviewed_aggregate.directory_sha256
    ):
        raise ValueError("v0.5 reviewed aggregate inventory mismatch")
    for prediction_artifact in inputs.predictions.artifacts:
        first = inputs.run_a.root / prediction_artifact.relative_path
        second = inputs.run_b.root / prediction_artifact.relative_path
        if (
            sha256_file(first) != prediction_artifact.sha256
            or sha256_file(second) != prediction_artifact.sha256
        ):
            raise ValueError("frozen prediction counterpart hash mismatch")
    for nearest_artifact in inputs.nearest_homolog.artifacts:
        first = inputs.run_a.root / nearest_artifact.relative_path
        second = inputs.run_b.root / nearest_artifact.relative_path
        if (
            sha256_file(first) != nearest_artifact.sha256
            or sha256_file(second) != nearest_artifact.sha256
        ):
            raise ValueError("frozen nearest-homolog counterpart hash mismatch")


def _verify_config_binding(
    config: PostTestAnalysisConfig,
    config_path: Path,
    attestation: AnalysisFreezeAttestation,
    root: Path,
    *,
    observed_software_version: str,
    observed_python_version: str,
) -> None:
    revision = "-r1" if config.name == "v060-post-test-analysis-r1" else ""
    protocol_logical = f"docs/protocols/v0.6.0-post-test-analysis{revision}.md"
    configuration_logical = f"configs/analysis/v060-post-test-analysis{revision}.yaml"
    expected = {
        "protocol": (
            attestation.protocol,
            protocol_logical,
            root / protocol_logical,
        ),
        "configuration": (
            attestation.code.configuration,
            configuration_logical,
            config_path,
        ),
        "uv_lock": (attestation.code.uv_lock, "uv.lock", root / "uv.lock"),
        "dependency_diff": (
            attestation.code.dependency_diff,
            "docs/audits/v0.6.0-dependency-diff.md",
            root / "docs/audits/v0.6.0-dependency-diff.md",
        ),
    }
    for name, (artifact, logical, physical) in expected.items():
        if artifact.path.as_posix() != logical or artifact.sha256 != sha256_file(physical):
            raise ValueError(f"attested {name} identity mismatch")
    frozen = attestation.frozen_inputs
    configured_split_hashes = {item.name: item.file_sha256 for item in config.inputs.splits}
    if (
        frozen.v050_attestation_sha256 != config.inputs.v050_attestation.sha256
        or frozen.v050_replay_sha256 != config.inputs.replay_report.sha256
        or frozen.run_a_directory_sha256 != config.inputs.run_a.directory_sha256
        or frozen.run_b_directory_sha256 != config.inputs.run_b.directory_sha256
        or frozen.prediction_inventory_sha256 != config.inputs.predictions.inventory_sha256
        or frozen.nearest_homolog_inventory_sha256 != config.inputs.nearest_homolog.inventory_sha256
        or frozen.combined_analysis_inventory_sha256
        != config.inputs.combined_analysis_inventory_sha256
        or frozen.cohort_file_sha256 != config.inputs.cohort.file_sha256
        or frozen.split_file_sha256.model_dump() != configured_split_hashes
    ):
        raise ValueError("attested frozen input identity mismatch")
    if (
        attestation.analysis.methods != config.methods
        or attestation.analysis.splits != config.splits
        or attestation.analysis.label_order != config.label_order
        or attestation.analysis.formal_sessions != config.outputs.formal_sessions
    ):
        raise ValueError("attested analysis definition mismatch")
    if (
        attestation.strata != config.strata
        or attestation.comparisons != config.comparisons
        or attestation.statistics != config.statistics
        or attestation.reporting != config.reporting
        or attestation.privacy != config.privacy
        or attestation.publication.public_artifacts != config.outputs.public_artifacts
        or attestation.publication.refuse_overwrite != config.outputs.refuse_overwrite
    ):
        raise ValueError("attested analysis policy mismatch")
    if attestation.runtime.model_dump() != {
        "operating_system": config.runtime.operating_system,
        "architecture": config.runtime.architecture,
        "python": config.runtime.python,
        "device": config.runtime.device,
        "network_access": config.runtime.network_access,
        "model_execution": config.runtime.model_execution,
    }:
        raise ValueError("attested runtime identity mismatch")
    if (
        observed_software_version != attestation.code.software_version
        or observed_python_version != attestation.code.python_version
    ):
        raise ValueError("attested software identity mismatch")


def verify_analysis_authorization(
    config_path: Path,
    attestation_path: Path,
    project_root: Path,
    *,
    observed_software_version: str = __version__,
    observed_python_version: str = platform.python_version(),
    git_verifier: Callable[[Path, Path, AnalysisFreezeAttestation], str] = _verify_git_binding,
    frozen_input_verifier: Callable[[PostTestAnalysisConfig], None] = verify_frozen_input_hashes,
) -> VerifiedAnalysisAuthorization:
    """Issue frozen-output authority only after metadata and opaque-byte gates pass."""

    try:
        root = project_root.resolve()
        resolved_config = config_path.resolve()
        resolved_attestation = attestation_path.resolve()
        if not resolved_config.is_relative_to(root) or not resolved_attestation.is_relative_to(
            root
        ):
            raise ValueError("analysis configuration and attestation must be inside project root")
        config = load_analysis_config(resolved_config)
        if config.attestation != resolved_attestation:
            raise ValueError("analysis attestation path differs from the frozen configuration")
        loaded = yaml.safe_load(resolved_attestation.read_text(encoding="utf-8"))
        attestation = AnalysisFreezeAttestation.model_validate(loaded)
        _verify_config_binding(
            config,
            resolved_config,
            attestation,
            root,
            observed_software_version=observed_software_version,
            observed_python_version=observed_python_version,
        )
        execution = git_verifier(root, resolved_attestation, attestation)
        frozen_input_verifier(config)
        frozen_hashes = {
            "v050_attestation": config.inputs.v050_attestation.sha256,
            "v050_replay": config.inputs.replay_report.sha256,
            "run_a": config.inputs.run_a.directory_sha256,
            "run_b": config.inputs.run_b.directory_sha256,
            "predictions": config.inputs.predictions.inventory_sha256,
            "nearest_homolog": config.inputs.nearest_homolog.inventory_sha256,
            "cohort": config.inputs.cohort.file_sha256,
        }
        return VerifiedAnalysisAuthorization(
            attestation_path=resolved_attestation,
            attestation_sha256=sha256_file(resolved_attestation),
            generation_commit=attestation.code.generation_git_commit,
            execution_commit=execution,
            approval_reference=attestation.approval.approval_reference,
            canonical_prediction_session="run-a",
            replay_evidence_session="run-b",
            formal_sessions=attestation.analysis.formal_sessions,
            protocol_sha256=attestation.protocol.sha256,
            config_sha256=attestation.code.configuration.sha256,
            lock_sha256=attestation.code.uv_lock.sha256,
            frozen_hashes=frozen_hashes,
            _token=_CAPABILITY_TOKEN,
        )
    except AnalysisOutputAccessDenied:
        raise
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        raise AnalysisOutputAccessDenied(
            "Frozen Test-output analysis is not authorized by the active v0.6 attestation"
        ) from error


def require_verified_analysis_authorization(authorization: object) -> None:
    """Reject manually constructed or forged analysis capabilities."""

    if (
        not isinstance(authorization, VerifiedAnalysisAuthorization)
        or authorization._token is not _CAPABILITY_TOKEN
    ):
        raise AnalysisOutputAccessDenied(
            "Frozen Test-output analysis is not authorized by the active v0.6 attestation"
        )


__all__ = [
    "AnalysisFreezeAttestation",
    "AnalysisOutputAccessDenied",
    "VerifiedAnalysisAuthorization",
    "require_verified_analysis_authorization",
    "verify_analysis_authorization",
    "verify_frozen_input_hashes",
]
