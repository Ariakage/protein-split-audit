# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import yaml

from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
EXPECTED_UPSTREAM = {
    "c8066a1851e83c95a3063f896236603cb41df085308e795fb42499ec7a0002da",
    "304d126e603a6361684dc76320f8c8e508ad5d9c7917a33052cd52fd5263ead1",
    "748cf1746d34daa17be2513744cc194e5aa2867edb0469388d68152080ddf9b9",
    "ff572a4eb81f5f377acc348a7fda9786ad773eea6131b54bad88a2b167e5e859",
    "80ed5a977b3111833f2f87a26bc11fa423a31e1976ea67f6b97e65414c7e898b",
    "898bd302cc77d157f0f4bd398ddc7ec40f9ef5eae43bbb3705963c7ba10ae74e",
    "bb2744886a6631f888eaa79028403b0ce6a41621235c68d16946e367bea837ab",
    "4c105e4b5c007830cf6916e566cebffa8ba1cb54572d59496def086b76eef0b2",
    "640e8d84fa84081d124cd6a37171351913f34b6a85a388af0b88f8d105b39023",
    "7d951338073d8958a0852c33c8910c14f8d7ae55e0892ee4ab5f4f1e4c347bee",
    "c0a40a89888f813bfa1173dfb9e66089ed4d8489c55bab6a7aaff1645132535c",
}
EXPECTED_RELEASE_HASHES = {
    "classical_vs_esm_summary.csv": (
        "d73af232cf5dedb675fff931391c35aa326d0e526a42a0bbb83d1d7e45fa894c"
    ),
    "embedding_feature_schema.json": (
        "10d3cff11abdb3af5d4c7abf9818f7eaba37c7c0b2920176187b446c5afffdf1"
    ),
    "environment_summary.json": (
        "1ab0412f055c5b375bd4c5931e5b2276fcd859c3cc31b4cfcf227935cf4bee15"
    ),
    "esm_validation_per_class.csv": (
        "8af608fd622acc2634b82c677f1f51c9aff63c5ae7977b4ab738d0ba14faa7f9"
    ),
    "esm_validation_summary.csv": (
        "2e96c04dc18695649ad51cf1fe9ee5b7a9c41fe4974a71d6e652b7d3ef4f5b6f"
    ),
    "model_snapshot_hashes.json": (
        "8d9afaf801eaf2c0db114e3786363dceef3273497ad77311673c064c7c0efcda"
    ),
}


def test_release_c_binds_attestation_and_reviewed_aggregates() -> None:
    attestation_path = PROJECT_ROOT / "docs/attestations/v0.4.0-protocol-freeze.yaml"
    attestation = yaml.safe_load(attestation_path.read_text(encoding="utf-8"))
    assert attestation["code"] == {
        "generation_git_commit": "d764c30c0945231113f2f51cdb9761ab62815c73",
        "generation_git_dirty": False,
        "software_version": "0.4.0",
        "uv_lock_sha256": "f924d6965ea4272e6f9faa378b19e57502a9a4feeab6918122a873588919d346",
        "python_version": "3.12.11",
    }
    assert attestation["protocol"] == {
        "path": "docs/protocols/v0.4.0-esm2-baselines.md",
        "sha256": "b23329c1d76558d30e80dba6563525624f00d14a1fe22a75baaca23ffc504694",
    }
    assert attestation["experiment"]["real_test_access_authorized"] is False
    assert attestation["approval"] == {
        "approved_by": "Ariakage",
        "approved_at_utc": "2026-07-16T04:55:21Z",
        "approval_reference": (
            "https://github.com/Ariakage/protein-split-audit/pull/2#issuecomment-4988328840"
        ),
        "author_association": "OWNER",
    }
    release_root = PROJECT_ROOT / "results/released/v0.4.0"
    assert {path.name for path in release_root.iterdir()} == {
        "README.md",
        "protocol_attestation.yaml",
        *EXPECTED_RELEASE_HASHES,
    }
    for name, expected_hash in EXPECTED_RELEASE_HASHES.items():
        assert sha256_file(release_root / name) == expected_hash
    attestation_sha256 = "ddeed606f308363a457e3edf0646275f788eae657778de03c86c3eed9bb214f7"
    assert sha256_file(attestation_path) == attestation_sha256
    assert sha256_file(release_root / "protocol_attestation.yaml") == attestation_sha256

    release_notes = (PROJECT_ROOT / "docs/releases/v0.4.0.md").read_text(encoding="utf-8")
    assert "Validation-only" in release_notes
    assert "real_test_access_authorized: false" in release_notes
    assert "issuecomment-4988328840" in release_notes
    assert "issuecomment-4988568957" in release_notes
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "version: 0.4.0" in citation
    assert "date-released: 2026-07-16" in citation


def test_release_c_directory_has_no_private_paths_or_sensitive_headers() -> None:
    release_root = PROJECT_ROOT / "results/released/v0.4.0"
    forbidden_text = (
        "/Users/",
        "file://",
        "Authorization:",
        "Bearer ",
        "api_key",
        "set-cookie",
    )
    for path in release_root.iterdir():
        content = path.read_text(encoding="utf-8")
        assert all(value not in content for value in forbidden_text)


def test_attestation_b_recomputes_all_tracked_frozen_hashes() -> None:
    attestation = yaml.safe_load(
        (PROJECT_ROOT / "docs/attestations/v0.4.0-protocol-freeze.yaml").read_text(encoding="utf-8")
    )
    tracked_artifacts = [
        attestation["protocol"],
        attestation["upstream"]["protocol_attestation"],
        attestation["upstream"]["validation_summary"],
        attestation["models"]["esm2_35m"]["embedding_config"],
        attestation["models"]["esm2_35m"]["snapshot_manifest"],
        attestation["models"]["esm2_150m"]["embedding_config"],
        attestation["models"]["esm2_150m"]["snapshot_manifest"],
        {
            "path": attestation["experiment"]["configuration_path"],
            "sha256": attestation["experiment"]["configuration_sha256"],
        },
        {
            "path": attestation["experiment"]["linear_probe_configuration_path"],
            "sha256": attestation["experiment"]["linear_probe_configuration_sha256"],
        },
    ]
    for artifact in tracked_artifacts:
        assert sha256_file(PROJECT_ROOT / artifact["path"]) == artifact["sha256"]

    input_artifacts = [
        attestation["inputs"]["cohort_manifest"],
        attestation["inputs"]["cohort_content_manifest"],
        attestation["inputs"]["cohort_fasta"],
    ]
    for split in attestation["inputs"]["split_manifests"].values():
        input_artifacts.extend(
            (
                {"path": split["path"], "sha256": split["sha256"]},
                {
                    "path": split["content_manifest_path"],
                    "sha256": split["content_manifest_sha256"],
                },
            )
        )
    assert len(input_artifacts) == 11
    for artifact in input_artifacts:
        path = PROJECT_ROOT / artifact["path"]
        if path.exists():
            assert sha256_file(path) == artifact["sha256"]

    for model_name in ("esm2_35m", "esm2_150m"):
        model = attestation["models"][model_name]
        snapshot = json.loads((PROJECT_ROOT / model["snapshot_manifest"]["path"]).read_bytes())
        assert snapshot["repository"] == model["repository"]
        assert snapshot["revision"] == model["revision"] == model["tokenizer_revision"]
        assert snapshot["snapshot_sha256"] == model["snapshot_sha256"]
        assert snapshot["tokenizer_sha256"] == model["tokenizer_sha256"]
        assert snapshot["model_weight_sha256"] == model["model_weight_sha256"]
        assert [
            {
                "path": item["relative_path"],
                "byte_size": item["byte_size"],
                "sha256": item["sha256"],
            }
            for item in snapshot["files"]
        ] == model["files"]


def test_v040_test_gate_and_model_snapshot_identities_are_frozen() -> None:
    test_config = yaml.safe_load(
        (PROJECT_ROOT / "configs/experiment/v040-test-gated.yaml").read_text(encoding="utf-8")
    )
    assert test_config["evaluation"] == {
        "split": "test",
        "label_order_from_cohort": True,
        "zero_division": 0,
        "real_test_access_authorized": False,
    }

    for name in ("esm2-35m.snapshot.json", "esm2-150m.snapshot.json"):
        manifest = json.loads((PROJECT_ROOT / "data/manifests/models" / name).read_bytes())
        assert len(manifest["revision"]) == 40
        assert len(manifest["model_weight_sha256"]) == 64
        assert len(manifest["snapshot_sha256"]) == 64
        assert {item["relative_path"] for item in manifest["files"]} == {
            "config.json",
            "model.safetensors",
            "special_tokens_map.json",
            "tokenizer_config.json",
            "vocab.txt",
        }


def test_restoration_audit_binds_all_v030_upstream_hashes() -> None:
    audit = (PROJECT_ROOT / "docs/audits/v0.4.0-frozen-input-restoration.md").read_text(
        encoding="utf-8"
    )
    assert all(value in audit for value in EXPECTED_UPSTREAM)
    assert sha256_file(PROJECT_ROOT / "results/released/v0.3.0/validation_summary.csv") == (
        "73ee1c4f8c454a8570058224c9257d4f924eac8c8681fcb78991d99fa6612dc2"
    )
