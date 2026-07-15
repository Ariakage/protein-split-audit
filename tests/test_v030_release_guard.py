# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import yaml

from protein_split_audit import __version__

PROJECT_ROOT = Path(__file__).parents[1]


def test_v030_development_state_has_no_premature_release_or_attestation() -> None:
    assert __version__ == "0.3.0"
    assert not (PROJECT_ROOT / "results/released/v0.3.0").exists()
    assert not (PROJECT_ROOT / "docs/attestations/v0.3.0-protocol-freeze.yaml").exists()
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "version: 0.2.0" in citation
    assert "version: 0.3.0" not in citation


def test_v030_test_configuration_keeps_real_test_access_false() -> None:
    mapping = yaml.safe_load(
        (PROJECT_ROOT / "configs/experiment/v030-test.yaml").read_text(encoding="utf-8")
    )
    assert mapping["evaluation"]["split"] == "test"
    assert mapping["evaluation"]["real_test_access_authorized"] is False
