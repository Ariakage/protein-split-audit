# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.config import load_analysis_config

PROJECT_ROOT = Path(__file__).parents[1]
PROTOCOL = PROJECT_ROOT / "docs/protocols/v0.6.0-post-test-analysis.md"
CONFIG = PROJECT_ROOT / "configs/analysis/v060-post-test-analysis.yaml"


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
