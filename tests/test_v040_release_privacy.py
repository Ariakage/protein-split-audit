# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protein_split_audit.experiments.aggregate import write_esm_validation_aggregates
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
CLASSICAL_SUMMARY = PROJECT_ROOT / "results/released/v0.3.0/validation_summary.csv"
CLASSICAL_SHA256 = "73ee1c4f8c454a8570058224c9257d4f924eac8c8681fcb78991d99fa6612dc2"


def _write_cell(root: Path, split: str, model: str, environment: dict[str, object]) -> None:
    cell = root / f"v040__{split}__{model}"
    cell.mkdir(parents=True)
    files = {
        "metrics.json": json.dumps(
            {
                "accuracy": 0.5,
                "balanced_accuracy": 0.5,
                "macro_f1": 0.5,
                "macro_precision": 0.5,
                "macro_recall": 0.5,
                "prediction_coverage": 1.0,
            },
            sort_keys=True,
        )
        + "\n",
        "per_class_metrics.csv": "label,support,precision,recall,f1\n1.1,1,0.5,0.5,0.5\n",
        "model_snapshot_manifest.json": json.dumps(
            {"snapshot_sha256": ("1" if model == "esm2_35m" else "2") * 64},
            sort_keys=True,
        )
        + "\n",
        "embedding_manifest.json": json.dumps(
            {"dtype": "float32", "hidden_size": 8, "pooling": "residue_mean"},
            sort_keys=True,
        )
        + "\n",
        "environment.json": json.dumps(environment, sort_keys=True) + "\n",
    }
    for name, content in files.items():
        (cell / name).write_text(content, encoding="utf-8", newline="\n")
    complete = {
        "artifact_sha256": {name: sha256_file(cell / name) for name in sorted(files)},
        "evaluation_split": "validation",
        "model": model,
        "split": split,
        "test_labels_accessed": 0,
        "test_metrics_generated": 0,
        "test_sequence_count_processed": 0,
    }
    (cell / "COMPLETE.json").write_text(
        json.dumps(complete, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _matrix(root: Path, environment: dict[str, object]) -> Path:
    root.mkdir()
    for split in ("random", "cluster70", "cluster50", "cluster30"):
        for model in ("esm2_35m", "esm2_150m"):
            _write_cell(root, split, model, environment)
    return root


def test_esm_aggregate_rejects_private_or_secret_environment_fields(tmp_path: Path) -> None:
    matrix = _matrix(
        tmp_path / "matrix",
        {
            "architecture": "arm64",
            "operating_system": "Darwin",
            "private_path": str(tmp_path),
        },
    )

    with pytest.raises(ValueError, match="unapproved environment fields"):
        write_esm_validation_aggregates(
            matrix,
            tmp_path / "aggregate",
            classical_summary=CLASSICAL_SUMMARY,
            expected_classical_sha256=CLASSICAL_SHA256,
        )


def test_esm_aggregate_rejects_test_metric_fields(tmp_path: Path) -> None:
    matrix = _matrix(
        tmp_path / "matrix",
        {"architecture": "arm64", "operating_system": "Darwin"},
    )
    cell = next(path for path in matrix.iterdir() if path.is_dir())
    metrics_path = cell / "metrics.json"
    metrics = json.loads(metrics_path.read_bytes())
    metrics["test_accuracy"] = 0.9
    metrics_path.write_text(json.dumps(metrics, sort_keys=True) + "\n", encoding="utf-8")
    complete_path = cell / "COMPLETE.json"
    complete = json.loads(complete_path.read_bytes())
    complete["artifact_sha256"]["metrics.json"] = sha256_file(metrics_path)
    complete_path.write_text(json.dumps(complete, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Test fields"):
        write_esm_validation_aggregates(
            matrix,
            tmp_path / "aggregate",
            classical_summary=CLASSICAL_SUMMARY,
            expected_classical_sha256=CLASSICAL_SHA256,
        )
