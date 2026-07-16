# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from protein_split_audit.config import load_embedding_config

PROJECT_ROOT = Path(__file__).parents[1]


def _mapping() -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_id": "esm2_35m",
        "model": {
            "repository": "facebook/esm2_t12_35M_UR50D",
            "revision": "6fbf070e65b0b7291e7bbcd451118c216cff79d8",
            "tokenizer_revision": "6fbf070e65b0b7291e7bbcd451118c216cff79d8",
            "expected_weight_sha256": (
                "e35647818e0e064351d4531ed480d225a002567b4b2b93ad3a9246d753150fc0"
            ),
            "snapshot_root": "../../cache/models/huggingface/esm2_35m",
        },
        "representation": {
            "layer": "last",
            "pooling": "residue_mean",
            "exclude_special_tokens": True,
        },
        "sequence": {"minimum_length": 50, "maximum_length": 1000, "truncation": False},
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
        "cache": {"root": "../../cache/embeddings", "refuse_overwrite": True},
    }


def _write(tmp_path: Path, mapping: dict[str, object]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "embedding.yaml"
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8", newline="\n")
    return path


def test_official_embedding_configs_are_exact() -> None:
    small = load_embedding_config(PROJECT_ROOT / "configs/embedding/esm2_35m.yaml")
    large = load_embedding_config(PROJECT_ROOT / "configs/embedding/esm2_150m.yaml")

    assert small.model.revision == "6fbf070e65b0b7291e7bbcd451118c216cff79d8"
    assert large.model.revision == "a695f6045e2e32885fa60af20c13cb35398ce30c"
    assert small.batching.max_padded_tokens == 4096
    assert large.batching.max_padded_tokens == 2048
    assert small.runtime.model_dump() == large.runtime.model_dump()
    assert small.runtime.device == "cpu"
    assert small.runtime.torch_intraop_threads == 8
    assert small.runtime.torch_interop_threads == 1


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("model", "revision"), "main", "40-character immutable revision"),
        (("model", "revision"), "6fbf070e", "40-character immutable revision"),
        (("model", "tokenizer_revision"), "0" * 40, "model and tokenizer revisions"),
        (("model", "expected_weight_sha256"), "0" * 64, "approved weight SHA-256"),
        (("runtime", "device"), "mps", "formal runtime"),
        (("runtime", "operating_system"), "Linux", "formal runtime"),
        (("runtime", "torch_intraop_threads"), 4, "formal runtime"),
        (("runtime", "torch_interop_threads"), 2, "formal runtime"),
        (("runtime", "deterministic_algorithms"), False, "formal runtime"),
        (("runtime", "local_files_only"), False, "formal runtime"),
        (("sequence", "truncation"), True, "truncation"),
        (("batching", "max_padded_tokens"), 2048, "approved padded-token budget"),
    ],
)
def test_embedding_config_rejects_protocol_changes(
    tmp_path: Path, path: tuple[str, str], value: object, message: str
) -> None:
    mapping = deepcopy(_mapping())
    section = mapping[path[0]]
    assert isinstance(section, dict)
    section[path[1]] = value

    with pytest.raises(ValidationError, match=message):
        load_embedding_config(_write(tmp_path, mapping))


def test_embedding_paths_are_config_relative(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "nested", _mapping())
    config = load_embedding_config(config_path)

    assert (
        config.model.snapshot_root
        == (config_path.parent / "../../cache/models/huggingface/esm2_35m").resolve()
    )
    assert config.cache.root == (config_path.parent / "../../cache/embeddings").resolve()
