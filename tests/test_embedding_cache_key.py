# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.config import load_embedding_config
from protein_split_audit.embeddings.cache import embedding_cache_key
from protein_split_audit.embeddings.schemas import ModelSnapshotManifest
from protein_split_audit.features.validation import load_feature_inputs
from tests.v030_helpers import write_tiny_inputs

PROJECT_ROOT = Path(__file__).parents[1]


def _bundle(tmp_path: Path):  # type: ignore[no-untyped-def]
    inputs = write_tiny_inputs(tmp_path)
    return load_feature_inputs(
        cohort_manifest=inputs.cohort,
        cohort_content_manifest=inputs.cohort_content,
        cohort_fasta=inputs.fasta,
        split_manifest=inputs.split,
        split_content_manifest=inputs.split_content,
    )


def _snapshot() -> ModelSnapshotManifest:
    return ModelSnapshotManifest(
        model_id="esm2_35m",
        repository="facebook/esm2_t12_35M_UR50D",
        revision="6fbf070e65b0b7291e7bbcd451118c216cff79d8",
        config_sha256="1" * 64,
        tokenizer_sha256="2" * 64,
        model_weight_sha256="3" * 64,
        snapshot_sha256="4" * 64,
        files=(),
    )


def test_embedding_cache_key_changes_with_runtime_dependency_or_input(tmp_path: Path) -> None:
    config = load_embedding_config(PROJECT_ROOT / "configs/embedding/esm2_35m.yaml")
    bundle = _bundle(tmp_path)
    versions = {
        "python": "3.12.11",
        "torch": "2.13.0",
        "transformers": "5.13.1",
        "tokenizers": "0.22.2",
        "safetensors": "0.8.0",
    }
    original = embedding_cache_key(config, _snapshot(), bundle, "random", versions)

    assert original != embedding_cache_key(
        config,
        _snapshot().model_copy(update={"snapshot_sha256": "5" * 64}),
        bundle,
        "random",
        versions,
    )
    assert original != embedding_cache_key(
        config,
        _snapshot(),
        bundle,
        "random",
        {**versions, "torch": "different"},
    )
    assert original != embedding_cache_key(config, _snapshot(), bundle, "cluster30", versions)
