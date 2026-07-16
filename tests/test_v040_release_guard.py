# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from protein_split_audit import __version__
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


def test_generation_a_has_no_attestation_results_tag_or_release_metadata() -> None:
    assert __version__ == "0.4.0"
    assert not (PROJECT_ROOT / "docs/attestations/v0.4.0-protocol-freeze.yaml").exists()
    assert not (PROJECT_ROOT / "results/released/v0.4.0").exists()
    assert not (PROJECT_ROOT / "docs/releases/v0.4.0.md").exists()
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "version: 0.3.0" in citation
    assert "version: 0.4.0" not in citation
    tag = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/tags/v0.4.0"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tag.returncode != 0


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
