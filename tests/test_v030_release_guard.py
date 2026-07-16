# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v030_release_is_bound_to_the_approved_validation_freeze() -> None:
    attestation_path = PROJECT_ROOT / "docs/attestations/v0.3.0-protocol-freeze.yaml"
    release_dir = PROJECT_ROOT / "results/released/v0.3.0"
    attestation = yaml.safe_load(attestation_path.read_text(encoding="utf-8"))

    assert attestation["release_target"] == "v0.3.0"
    assert attestation["code"]["git_commit"] == ("aa6305784706c36bfd1a198ad7d7c3b374d31807")
    assert attestation["code"]["git_dirty"] is False
    assert attestation["experiment"]["evaluation_split"] == "validation"
    assert attestation["experiment"]["real_test_access_authorized"] is False
    assert attestation["approval"]["approval_reference"] == (
        "https://github.com/Ariakage/protein-split-audit/pull/1#issuecomment-4981819750"
    )
    assert (
        _sha256(PROJECT_ROOT / attestation["protocol"]["path"])
        == (attestation["protocol"]["sha256"])
    )
    assert attestation["code"]["uv_lock_sha256"] == (
        "99dc065b3279746c80d30fecc672694d970715417365d1bc31471e61e190e815"
    )

    for artifact in attestation["review"]["released_aggregates"].values():
        assert _sha256(PROJECT_ROOT / artifact["path"]) == artifact["sha256"]

    assert sorted(path.name for path in release_dir.iterdir()) == [
        "README.md",
        "environment_summary.json",
        "feature_schema.json",
        "protocol_attestation.yaml",
        "validation_per_class.csv",
        "validation_summary.csv",
    ]
    assert (release_dir / "protocol_attestation.yaml").read_bytes() == attestation_path.read_bytes()
    assert not any(path.name.casefold().startswith("test_") for path in release_dir.iterdir())

    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "version: 0.3.0" in citation
    assert "date-released: 2026-07-15" in citation


def test_v030_test_configuration_keeps_real_test_access_false() -> None:
    mapping = yaml.safe_load(
        (PROJECT_ROOT / "configs/experiment/v030-test.yaml").read_text(encoding="utf-8")
    )
    assert mapping["evaluation"]["split"] == "test"
    assert mapping["evaluation"]["real_test_access_authorized"] is False
