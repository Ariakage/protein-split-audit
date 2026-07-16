# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
PROTOCOL = PROJECT_ROOT / "docs/protocols/v0.4.0-esm2-baselines.md"


def test_v040_protocol_records_every_frozen_identity_and_boundary() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")

    required = (
        "facebook/esm2_t12_35M_UR50D",
        "6fbf070e65b0b7291e7bbcd451118c216cff79d8",
        "e35647818e0e064351d4531ed480d225a002567b4b2b93ad3a9246d753150fc0",
        "facebook/esm2_t30_150M_UR50D",
        "a695f6045e2e32885fa60af20c13cb35398ce30c",
        "c3f1da8aea53bddd32c246c86168c23b9fd72341fb9db9a94436f855f5053566",
        "EsmForMaskedLM",
        ".esm",
        "residue",
        "BOS",
        "EOS",
        "4096",
        "2048",
        "Darwin",
        "arm64",
        "float32",
        "StandardScaler",
        "Validation",
        "real_test_access_authorized: false",
        "rtol=1e-5",
        "atol=1e-6",
        "Generation Commit A",
        "Attestation Commit B",
        "Release Commit C",
    )
    for value in required:
        assert value in text

    assert "pretraining-corpus contamination is not audited" in text
    assert "cannot be claimed unseen during pretraining" in text


def test_v040_protocol_names_exact_snapshot_allowlist() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")

    for name in (
        "config.json",
        "model.safetensors",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.txt",
    ):
        assert name in text
    assert "actual file set must equal" in text
