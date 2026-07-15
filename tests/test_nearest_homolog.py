# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from protein_split_audit.config import load_model_config
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.schemas import NearestHomologModelConfig

PROJECT_ROOT = Path(__file__).parents[1]


def _record(accession: str, label: str, split: str) -> SequenceRecord:
    return SequenceRecord(accession, b"0" * 32, label, split, "ACDE")


def test_nearest_hit_sort_uses_evalue_after_bitscore() -> None:
    from protein_split_audit.models.nearest_homolog import HomologHit, predict_nearest

    records = (
        _record("T1", "1.1", "train"),
        _record("T2", "2.7", "train"),
        _record("V1", "1.1", "validation"),
    )
    hits = (
        HomologHit("V1", "T1", 0.90, 0.90, 0.90, 1e-4, 100.0),
        HomologHit("V1", "T2", 0.80, 0.90, 0.90, 1e-6, 100.0),
    )

    result = predict_nearest(records, hits)

    assert result.rows[0].nearest_train_accession == "T2"
    assert result.rows[0].predicted_label == "2.7"
    assert result.rows[0].no_hit is False


def test_no_hit_is_explicit_training_majority_fallback() -> None:
    from protein_split_audit.models.nearest_homolog import predict_nearest

    records = (
        _record("T1", "1.1", "train"),
        _record("T2", "1.1", "train"),
        _record("T3", "2.7", "train"),
        _record("V1", "1.1", "validation"),
    )

    result = predict_nearest(records, ())

    assert result.rows[0].predicted_label == "1.1"
    assert result.rows[0].no_hit is True
    assert result.no_hit_count == 1
    assert result.no_hit_rate == 1.0
    assert result.no_hit_correct_count == 1


def test_nearest_rejects_non_validation_query() -> None:
    from protein_split_audit.models.nearest_homolog import HomologHit, predict_nearest

    records = (_record("T1", "1.1", "train"), _record("X1", "1.1", "test"))
    with pytest.raises(ValueError, match="Validation"):
        predict_nearest(records, (HomologHit("X1", "T1", 0.9, 0.9, 0.9, 1e-6, 10.0),))


def test_nearest_command_is_frozen_and_train_only(tmp_path: Path) -> None:
    from protein_split_audit.models.nearest_homolog import build_nearest_argv

    config = load_model_config(PROJECT_ROOT / "configs/model/nearest_homolog.yaml")
    assert isinstance(config, NearestHomologModelConfig)
    argv = build_nearest_argv(
        config,
        query_fasta=(tmp_path / "validation.fasta").resolve(),
        target_fasta=(tmp_path / "train.fasta").resolve(),
        output_tsv=(tmp_path / "hits.tsv").resolve(),
        temp_dir=(tmp_path / "tmp").resolve(),
        train_count=3,
    )

    assert argv[:6] == (
        "mmseqs",
        "easy-search",
        str((tmp_path / "validation.fasta").resolve()),
        str((tmp_path / "train.fasta").resolve()),
        str((tmp_path / "hits.tsv").resolve()),
        str((tmp_path / "tmp").resolve()),
    )
    assert argv[argv.index("--threads") + 1] == "8"
    assert argv[argv.index("-e") + 1] == "0.001"
    assert argv[argv.index("-c") + 1] == "0.80"
