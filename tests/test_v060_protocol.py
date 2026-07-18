# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.config import load_analysis_config
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
PROTOCOL = PROJECT_ROOT / "docs/protocols/v0.6.0-post-test-analysis.md"
CONFIG = PROJECT_ROOT / "configs/analysis/v060-post-test-analysis.yaml"
R1_PROTOCOL = PROJECT_ROOT / "docs/protocols/v0.6.0-post-test-analysis-r1.md"
R1_CONFIG = PROJECT_ROOT / "configs/analysis/v060-post-test-analysis-r1.yaml"
INCIDENT = PROJECT_ROOT / "docs/audits/v0.6.0-analysis-a-incident.md"


def test_v060_protocol_freezes_every_confirmatory_boundary() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    config = load_analysis_config(CONFIG)

    for heading in (
        "RQ1 — Performance by split",
        "RQ2 — Nearest-Train identity",
        "RQ3 — Sequence length",
        "RQ4 — Per-EC-class generalization",
        "RQ5 — ESM-2 versus classical features",
        "RQ6 — Nearest Homolog failure modes",
        "Confirmatory analyses",
        "Exploratory analyses",
        "Small-group and privacy rules",
        "Two-run analysis replay",
    ):
        assert heading in text

    for bin_id in (
        *(item.id for item in config.strata.identity_bins),
        *(item.id for item in config.strata.length_bins),
        *(item.id for item in config.strata.component_size_bins),
    ):
        assert f"`{bin_id}`" in text

    assert "2,000" in text
    assert "Cluster30 discovery component" in text
    assert "seed 2026" in text
    assert "new_test_inference_authorized: false" in text
    assert "frozen_test_output_analysis_authorized: true" in text
    assert "statistical significance" in text


def test_v060_protocol_denies_model_and_sequence_execution() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")

    for statement in (
        "No model is trained, loaded, or executed",
        "No Test inference is run",
        "The cohort FASTA is not read",
        "Run B is replay evidence only",
        "Exploratory outputs remain private",
    ):
        assert statement in text

    assert "new_test_inference_authorized: true" not in text


def test_v060_r1_protocol_changes_only_metadata_normalization_and_session_identity() -> None:
    text = R1_PROTOCOL.read_text(encoding="utf-8")
    incident = INCIDENT.read_text(encoding="utf-8")
    original = load_analysis_config(CONFIG)
    revised = load_analysis_config(R1_CONFIG)

    assert sha256_file(PROTOCOL) == (
        "ed84edec388e9c0c5c352f20e944fac7bb4e5c8e38059393d11257257ed4a402"
    )
    for statement in (
        "Revision r1 and incident boundary",
        "Frozen prediction-metadata normalization",
        "both `no_hit` and `nearest_train_identity` must be null",
        "authenticated Nearest Homolog detail artifact supplies the canonical",
        "only formal sessions are `analysis-r1-a` followed immediately by",
        "`analysis-r1-b`. Their private roots",
        "Attestation Commit B2",
        "new_test_inference_authorized: false",
        "frozen_test_output_analysis_authorized: true",
    ):
        assert statement in text

    assert revised.inputs == original.inputs
    assert revised.strata == original.strata
    assert revised.comparisons == original.comparisons
    assert revised.statistics == original.statistics
    assert revised.reporting == original.reporting
    assert revised.privacy == original.privacy
    assert revised.outputs.public_artifacts == original.outputs.public_artifacts
    assert "new_test_inference_authorized: true" not in text
    assert "/Users/" not in text

    for evidence in (
        "525e77beeffdd16d68f59bd7fb410710d7ef7968",
        "42677427d0ec71042efd75ff6b617a69e3f1bf86eacfecb228fe0ee1922943d8",
        "918fe4ed610f31c326f8c610373944437434e82ac76ebaf05f6f556778ea75e3",
        "no `analysis-b` ledger",
        "no accession",
    ):
        assert evidence in incident
    assert "/Users/" not in incident
