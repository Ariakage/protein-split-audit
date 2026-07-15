# SPDX-License-Identifier: Apache-2.0

"""Timestamp-free top-level provenance for the complete v0.2 artifact graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type ArtifactKind = Literal[
    "pilot_cohort",
    "cluster70",
    "cluster50",
    "cluster30",
    "random_split",
    "cluster70_split",
    "cluster50_split",
    "cluster30_split",
    "random_audit",
    "cluster70_audit",
    "cluster50_audit",
    "cluster30_audit",
    "split_summary",
]

_ORDER: tuple[ArtifactKind, ...] = (
    "pilot_cohort",
    "cluster70",
    "cluster50",
    "cluster30",
    "random_split",
    "cluster70_split",
    "cluster50_split",
    "cluster30_split",
    "random_audit",
    "cluster70_audit",
    "cluster50_audit",
    "cluster30_audit",
    "split_summary",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class V020Artifact(_FrozenModel):
    """One exact child content manifest or aggregate summary identity."""

    kind: ArtifactKind
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_eligible: bool


class V020ContentManifest(_FrozenModel):
    """Complete deterministic v0.2 lineage without run-specific fields."""

    manifest_schema_version: Literal[1] = 1
    release_series: Literal["v0.2.0"] = "v0.2.0"
    artifacts: tuple[V020Artifact, ...]
    generation_git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    generation_git_dirty: bool
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    software_version: str
    release_eligible: bool
    ineligibility_reasons: tuple[str, ...]


def build_v020_content_manifest(
    artifacts: tuple[V020Artifact, ...],
    *,
    generation_git_commit: str,
    generation_git_dirty: bool,
    uv_lock_sha256: str,
    software_version: str,
) -> V020ContentManifest:
    """Bind every required child identity and compute the top-level release gate."""

    by_kind = {artifact.kind: artifact for artifact in artifacts}
    if len(by_kind) != len(artifacts):
        raise ValueError("v0.2 artifacts contain a duplicate kind")
    missing = tuple(kind for kind in _ORDER if kind not in by_kind)
    extra = tuple(kind for kind in by_kind if kind not in _ORDER)
    reasons: list[str] = []
    if missing:
        reasons.append("missing_required_artifacts")
    if extra:
        reasons.append("unknown_artifacts")
    if generation_git_dirty:
        reasons.append("generation_git_dirty")
    if any(not artifact.release_eligible for artifact in artifacts):
        reasons.append("child_not_release_eligible")
    ordered = tuple(by_kind[kind] for kind in _ORDER if kind in by_kind)
    return V020ContentManifest(
        artifacts=ordered,
        generation_git_commit=generation_git_commit,
        generation_git_dirty=generation_git_dirty,
        uv_lock_sha256=uv_lock_sha256,
        software_version=software_version,
        release_eligible=not reasons,
        ineligibility_reasons=tuple(reasons),
    )


def validate_release_eligibility(manifest: V020ContentManifest) -> None:
    """Fail unless the complete top-level manifest is formally release-eligible."""

    if not manifest.release_eligible or manifest.ineligibility_reasons:
        raise RuntimeError("v0.2 content manifest is not release eligible")
    if tuple(artifact.kind for artifact in manifest.artifacts) != _ORDER:
        raise RuntimeError("v0.2 content manifest artifact order or coverage is invalid")


__all__ = [
    "ArtifactKind",
    "V020Artifact",
    "V020ContentManifest",
    "build_v020_content_manifest",
    "validate_release_eligibility",
]
