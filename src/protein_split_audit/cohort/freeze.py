# SPDX-License-Identifier: Apache-2.0

"""Fail-closed validation for an externally authored cohort-freeze approval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from protein_split_audit.cohort.regeneration import CandidateLineage, RegenerationDifference
from protein_split_audit.cohort.schemas import SELECTION_RULE_VERSION
from protein_split_audit.provenance import (
    GitMetadata,
    serialize_canonical_json,
    sha256_bytes,
)


class FreezeGateError(RuntimeError):
    """Raised when reviewed freeze evidence is missing, stale, or inconsistent."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryFreezeLineage(_FrozenModel):
    """Sanitized fields extracted from a verified discovery content manifest."""

    content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fasta_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_git_commit: str | None
    generation_git_dirty: bool | None
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_eligible: bool
    ineligibility_reasons: tuple[str, ...]


class FreezeReview(_FrozenModel):
    """Canonical maintainer-authored attestation binding exact reviewed inputs."""

    review_schema_version: Literal[1] = 1
    review_rule_version: Literal["clean-regeneration-review-v1"] = "clean-regeneration-review-v1"
    decision: Literal["approved-for-pilot-v1-freeze"]
    selection_rule_version: Literal["pilot-ec2-5class-min40-c30g10-cap250-seed42-v1"]
    generation_git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_download_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    regenerated_download_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    regenerated_build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    difference_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_reference: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class FreezeEvidence:
    """Exact machine-validated evidence required to construct a frozen cohort."""

    cohort_version: Literal["pilot-v1"]
    generation_git_commit: str
    uv_lock_sha256: str
    difference_report_sha256: str
    review_attestation_sha256: str
    discovery_content_manifest_sha256: str
    approval_reference: str


def _report_manifest_hash(
    difference: RegenerationDifference,
    identity_name: Literal["historical_identity", "regenerated_identity"],
    field: Literal["download_manifest_sha256", "build_manifest_sha256"],
) -> str:
    identity = difference.report.get(identity_name)
    if not isinstance(identity, dict):
        raise FreezeGateError(f"freeze difference {identity_name} is missing")
    value = identity.get(field)
    if not isinstance(value, str):
        raise FreezeGateError(f"freeze difference {identity_name}.{field} is missing")
    return value


def validate_freeze_review(
    review: FreezeReview,
    *,
    difference: RegenerationDifference,
    historical: CandidateLineage | None,
    regenerated: CandidateLineage,
    discovery: DiscoveryFreezeLineage,
    current_git: GitMetadata,
    actual_uv_lock_sha256: str,
) -> FreezeEvidence:
    """Bind external approval to the exact clean lineage and current checkout."""

    if review.selection_rule_version != SELECTION_RULE_VERSION:
        raise FreezeGateError("freeze review selection rule is not the approved 40/5/10 rule")
    if not current_git.available or current_git.dirty is not False or current_git.commit is None:
        raise FreezeGateError("freeze requires a clean current Git checkout")
    if review.difference_report_sha256 != difference.aggregate_sha256:
        raise FreezeGateError("freeze review difference report hash is stale")
    historical_download_sha256 = _report_manifest_hash(
        difference, "historical_identity", "download_manifest_sha256"
    )
    historical_build_sha256 = _report_manifest_hash(
        difference, "historical_identity", "build_manifest_sha256"
    )
    regenerated_download_sha256 = _report_manifest_hash(
        difference, "regenerated_identity", "download_manifest_sha256"
    )
    regenerated_build_sha256 = _report_manifest_hash(
        difference, "regenerated_identity", "build_manifest_sha256"
    )
    if historical is not None and (
        historical.download_manifest_sha256 != historical_download_sha256
        or historical.build_manifest_sha256 != historical_build_sha256
    ):
        raise FreezeGateError("freeze difference historical identity is stale")
    if (
        regenerated.download_manifest_sha256 != regenerated_download_sha256
        or regenerated.build_manifest_sha256 != regenerated_build_sha256
    ):
        raise FreezeGateError("freeze difference regenerated identity is stale")
    if review.historical_download_manifest_sha256 != historical_download_sha256:
        raise FreezeGateError("freeze review historical download identity is stale")
    if review.historical_build_manifest_sha256 != historical_build_sha256:
        raise FreezeGateError("freeze review historical build identity is stale")
    if review.regenerated_download_manifest_sha256 != regenerated.download_manifest_sha256:
        raise FreezeGateError("freeze review regenerated download identity is stale")
    if review.regenerated_build_manifest_sha256 != regenerated.build_manifest_sha256:
        raise FreezeGateError("freeze review regenerated build identity is stale")

    commits = {
        review.generation_git_commit,
        regenerated.download_manifest.git_commit,
        regenerated.build_manifest.git_commit,
        discovery.generation_git_commit,
        current_git.commit,
    }
    if None in commits or len(commits) != 1:
        raise FreezeGateError("freeze generation commit identities do not match")
    locks = {
        review.uv_lock_sha256,
        regenerated.download_manifest.uv_lock_sha256,
        regenerated.build_manifest.uv_lock_sha256,
        discovery.uv_lock_sha256,
        actual_uv_lock_sha256,
    }
    if len(locks) != 1:
        raise FreezeGateError("freeze uv.lock hashes do not match")
    if discovery.generation_git_dirty is not False:
        raise FreezeGateError("freeze discovery lineage is not clean")
    if not discovery.release_eligible or discovery.ineligibility_reasons:
        raise FreezeGateError("freeze discovery is not release-eligible")
    if review.discovery_content_manifest_sha256 != discovery.content_manifest_sha256:
        raise FreezeGateError("freeze review discovery identity is stale")
    if discovery.candidate_dataset_sha256 != regenerated.pool.dataset_sha256:
        raise FreezeGateError("freeze discovery candidate dataset identity is stale")
    if discovery.build_manifest_sha256 != regenerated.build_manifest_sha256:
        raise FreezeGateError("freeze discovery build identity is stale")
    if discovery.fasta_sha256 != regenerated.pool.fasta_sha256:
        raise FreezeGateError("freeze discovery FASTA identity is stale")

    review_bytes = serialize_canonical_json(review.model_dump(mode="json"))
    return FreezeEvidence(
        cohort_version="pilot-v1",
        generation_git_commit=review.generation_git_commit,
        uv_lock_sha256=review.uv_lock_sha256,
        difference_report_sha256=review.difference_report_sha256,
        review_attestation_sha256=sha256_bytes(review_bytes),
        discovery_content_manifest_sha256=review.discovery_content_manifest_sha256,
        approval_reference=review.approval_reference,
    )


__all__ = [
    "DiscoveryFreezeLineage",
    "FreezeEvidence",
    "FreezeGateError",
    "FreezeReview",
    "validate_freeze_review",
]
