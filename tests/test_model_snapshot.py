# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from protein_split_audit.embeddings.model_registry import (
    APPROVED_SNAPSHOT_FILES,
    build_snapshot_manifest,
    snapshot_file_index,
    verify_model_snapshot,
)
from protein_split_audit.embeddings.schemas import EmbeddingConfig

REVISION = "6fbf070e65b0b7291e7bbcd451118c216cff79d8"
WEIGHT_SHA = "e35647818e0e064351d4531ed480d225a002567b4b2b93ad3a9246d753150fc0"


def _config(root: Path) -> EmbeddingConfig:
    return EmbeddingConfig.model_validate(
        {
            "schema_version": 1,
            "model_id": "esm2_35m",
            "model": {
                "repository": "facebook/esm2_t12_35M_UR50D",
                "revision": REVISION,
                "tokenizer_revision": REVISION,
                "expected_weight_sha256": WEIGHT_SHA,
                "snapshot_root": root,
            },
            "representation": {
                "layer": "last",
                "pooling": "residue_mean",
                "exclude_special_tokens": True,
            },
            "sequence": {
                "minimum_length": 50,
                "maximum_length": 1000,
                "truncation": False,
            },
            "batching": {
                "max_padded_tokens": 4096,
                "ordering": "encoded_length_then_sequence_sha256",
            },
            "runtime": {
                "formal": True,
                "operating_system": "Darwin",
                "architecture": "arm64",
                "device": "cpu",
                "dtype": "float32",
                "torch_intraop_threads": 8,
                "torch_interop_threads": 1,
                "deterministic_algorithms": True,
                "local_files_only": True,
            },
            "cache": {"root": root.parent / "embeddings", "refuse_overwrite": True},
        }
    )


def _snapshot(root: Path) -> None:
    root.mkdir(parents=True)
    payloads = {
        "config.json": b"{}\n",
        "model.safetensors": b"synthetic-weight-bytes",
        "tokenizer_config.json": b"{}\n",
        "special_tokens_map.json": b"{}\n",
        "vocab.txt": b"<cls>\n<pad>\n<eos>\n<unk>\nA\n",
    }
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)


def test_snapshot_file_index_requires_exact_allowlist(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    _snapshot(root)

    index = snapshot_file_index(
        root,
        repository="facebook/esm2_t12_35M_UR50D",
        revision=REVISION,
        downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert tuple(item.relative_path for item in index) == APPROVED_SNAPSHOT_FILES
    assert all(item.repository == "facebook/esm2_t12_35M_UR50D" for item in index)
    assert all(item.revision == REVISION for item in index)

    (root / "README.md").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly the approved five files"):
        snapshot_file_index(
            root,
            repository="facebook/esm2_t12_35M_UR50D",
            revision=REVISION,
            downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_snapshot_file_index_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    _snapshot(root)
    (root / "vocab.txt").unlink()
    (root / "vocab.txt").symlink_to(root / "config.json")

    with pytest.raises(ValueError, match="regular files"):
        snapshot_file_index(
            root,
            repository="facebook/esm2_t12_35M_UR50D",
            revision=REVISION,
            downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_manifest_verification_detects_changed_bytes(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    _snapshot(root)
    config = _config(root)
    observed_weight_sha = (
        __import__("hashlib").sha256((root / "model.safetensors").read_bytes()).hexdigest()
    )
    config = config.model_copy(
        update={
            "model": config.model.model_copy(update={"expected_weight_sha256": observed_weight_sha})
        }
    )
    manifest = build_snapshot_manifest(
        config,
        downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
    )

    verify_model_snapshot(config, manifest)
    (root / "config.json").write_bytes(b'{"changed":true}\n')

    with pytest.raises(ValueError, match="snapshot file index mismatch"):
        verify_model_snapshot(config, manifest)
