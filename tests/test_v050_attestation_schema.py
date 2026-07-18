# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from protein_split_audit.attestations.test_access import (
    TestFreezeAttestation as FreezeAttestation,
)


def _mapping() -> dict[str, object]:
    digest = "a" * 64
    revision = "b" * 40
    return {
        "schema_version": 1,
        "project": "ProteinSplitAudit",
        "release_target": "v0.5.0",
        "attestation_type": "frozen_test_access",
        "protocol": {
            "path": "docs/protocols/v0.5.0-frozen-test-evaluation.md",
            "sha256": digest,
        },
        "code": {
            "generation_git_commit": revision,
            "generation_git_dirty": False,
            "software_version": "0.5.0",
            "python_version": "3.12.11",
            "configuration": {"path": "configs/experiment/v050-test.yaml", "sha256": digest},
            "uv_lock": {"path": "uv.lock", "sha256": digest},
            "dependency_diff": {
                "path": "docs/audits/v0.5.0-dependency-diff.md",
                "sha256": digest,
            },
        },
        "frozen": {
            "cohort": {
                "manifest": "data/manifests/cohorts/pilot-v1.parquet",
                "file_sha256": digest,
                "semantic_sha256": digest,
                "content_manifest": "data/manifests/cohorts/pilot-v1.json",
                "content_manifest_sha256": digest,
                "fasta": "data/processed/cohorts/pilot-v1.fasta",
                "fasta_sha256": digest,
                "row_count": 442,
                "bootstrap_component_column": "discovery_component_id_cluster30",
            },
            "splits": [
                {
                    "name": name,
                    "manifest": f"data/manifests/splits/{name}.parquet",
                    "file_sha256": digest,
                    "semantic_sha256": digest,
                    "content_manifest": f"data/manifests/splits/{name}.json",
                    "content_manifest_sha256": digest,
                    "train_count": 308,
                    "validation_count": 68,
                    "test_count": 66,
                }
                for name in ("random", "cluster70", "cluster50", "cluster30")
            ],
            "methods": [
                {"name": name, "config_paths": [f"configs/method/{name}.yaml"]}
                for name in (
                    "majority",
                    "length_logistic",
                    "aac_logistic",
                    "kmer3_logistic",
                    "nearest_homolog",
                    "esm2_35m",
                    "esm2_150m",
                )
            ],
            "tracked_evidence": [
                {"path": "docs/evidence.md", "sha256": digest},
            ],
            "model_snapshots": [
                {
                    "name": "esm2_35m",
                    "manifest": "data/manifests/models/esm2-35m.snapshot.json",
                    "manifest_sha256": digest,
                    "repository": "facebook/esm2_t12_35M_UR50D",
                    "revision": "6fbf070e65b0b7291e7bbcd451118c216cff79d8",
                    "canonical_snapshot_sha256": digest,
                    "tokenizer_sha256": digest,
                    "model_weight_sha256": digest,
                },
                {
                    "name": "esm2_150m",
                    "manifest": "data/manifests/models/esm2-150m.snapshot.json",
                    "manifest_sha256": digest,
                    "repository": "facebook/esm2_t30_150M_UR50D",
                    "revision": "a695f6045e2e32885fa60af20c13cb35398ce30c",
                    "canonical_snapshot_sha256": digest,
                    "tokenizer_sha256": digest,
                    "model_weight_sha256": digest,
                },
            ],
        },
        "experiment": {
            "methods": [
                "majority",
                "length_logistic",
                "aac_logistic",
                "kmer3_logistic",
                "nearest_homolog",
                "esm2_35m",
                "esm2_150m",
            ],
            "splits": ["random", "cluster70", "cluster50", "cluster30"],
            "matrix_cells": 28,
            "fit_partition": "train",
            "evaluation_partition": "test",
            "validation_policy": "excluded",
            "formal_sessions": ["run-a", "run-b"],
            "real_test_access_authorized": True,
        },
        "statistics": {
            "bootstrap": {
                "unit": "cluster30_discovery_component",
                "iterations": 2000,
                "confidence_level": 0.95,
                "interval_method": "percentile",
                "lower_quantile": 0.025,
                "upper_quantile": 0.975,
                "seed": 2026,
            },
            "within_split_resampling": "paired",
            "cross_split_resampling": "independent",
        },
        "runtime": {
            "operating_system": "Darwin",
            "architecture": "arm64",
            "python_version": "3.12.11",
            "device": "cpu",
            "dtype": "float32",
            "torch_intraop_threads": 8,
            "torch_interop_threads": 1,
            "deterministic_algorithms": True,
            "mmseqs_version": "18-8cc5c",
            "mmseqs_threads": 8,
            "local_files_only": True,
            "network_access": False,
            "dependency_versions": {
                "torch": "2.13.0",
                "transformers": "5.13.1",
                "safetensors": "0.8.0",
                "tokenizers": "0.22.2",
                "huggingface_hub": "1.23.0",
                "accelerate": "1.14.0",
            },
        },
        "approval": {
            "approved_by": "Ariakage",
            "approved_at_utc": "2026-07-16T12:00:00Z",
            "approval_reference": (
                "https://github.com/Ariakage/protein-split-audit/pull/3#issuecomment-5000000000"
            ),
            "author_association": "OWNER",
            "approval_comment_sha256": digest,
        },
    }


def test_v050_attestation_schema_accepts_only_the_complete_frozen_shape() -> None:
    attestation = FreezeAttestation.model_validate(_mapping())

    assert attestation.experiment.real_test_access_authorized is True
    assert attestation.experiment.formal_sessions == ("run-a", "run-b")
    assert attestation.experiment.matrix_cells == 28


@pytest.mark.parametrize(
    "mutation, message",
    (
        (lambda value: value.__setitem__("project", "Other"), "ProteinSplitAudit"),
        (
            lambda value: value["experiment"].__setitem__("real_test_access_authorized", False),
            "Input should be True",
        ),
        (
            lambda value: value["experiment"].__setitem__("formal_sessions", ["run-a"]),
            "formal sessions",
        ),
        (
            lambda value: value["approval"].__setitem__("approval_reference", "https://x.test"),
            "permanent GitHub",
        ),
        (
            lambda value: value["code"].__setitem__("generation_git_commit", "abc"),
            "string_pattern_mismatch",
        ),
        (lambda value: value.__setitem__("unexpected", True), "Extra inputs"),
    ),
)
def test_v050_attestation_schema_rejects_incomplete_or_changed_authority(
    mutation: object,
    message: str,
) -> None:
    mapping = deepcopy(_mapping())
    assert callable(mutation)
    mutation(mapping)

    with pytest.raises(ValidationError, match=message):
        FreezeAttestation.model_validate(mapping)
