# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest


def test_top_level_content_manifest_is_timestamp_free_and_hash_bound() -> None:
    from protein_split_audit.v020_provenance import (
        V020Artifact,
        build_v020_content_manifest,
        validate_release_eligibility,
    )

    artifacts = tuple(
        V020Artifact(kind=kind, manifest_sha256=f"{index:064x}", release_eligible=True)
        for index, kind in enumerate(
            (
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
            ),
            start=1,
        )
    )
    manifest = build_v020_content_manifest(
        artifacts,
        generation_git_commit="a" * 40,
        generation_git_dirty=False,
        uv_lock_sha256="b" * 64,
        software_version="0.2.0.dev0",
    )

    validate_release_eligibility(manifest)
    serialized = manifest.model_dump_json()
    assert "timestamp" not in serialized
    assert "/Users/" not in serialized
    assert manifest.release_eligible


def test_top_level_release_gate_rejects_dirty_or_partial_lineage() -> None:
    from protein_split_audit.v020_provenance import (
        V020Artifact,
        build_v020_content_manifest,
        validate_release_eligibility,
    )

    manifest = build_v020_content_manifest(
        (V020Artifact(kind="pilot_cohort", manifest_sha256="1" * 64, release_eligible=True),),
        generation_git_commit="a" * 40,
        generation_git_dirty=True,
        uv_lock_sha256="b" * 64,
        software_version="0.2.0.dev0",
    )

    with pytest.raises(RuntimeError, match="eligible"):
        validate_release_eligibility(manifest)
