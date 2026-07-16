# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from click import unstyle
from typer.testing import CliRunner

from protein_split_audit.cli import app
from protein_split_audit.experiments.aggregate import write_esm_validation_aggregates
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]


def _write_cell(root: Path, split: str, model: str) -> None:
    cell = root / f"v040__{split}__{model}"
    cell.mkdir(parents=True)
    files = {
        "metrics.json": json.dumps(
            {
                "accuracy": 0.5,
                "balanced_accuracy": 0.5,
                "label_order": ["1.1"],
                "macro_f1": 0.5,
                "macro_precision": 0.5,
                "macro_recall": 0.5,
                "no_hit_correct_count": 0,
                "no_hit_count": 0,
                "no_hit_rate": 0.0,
                "prediction_coverage": 1.0,
            },
            sort_keys=True,
        )
        + "\n",
        "per_class_metrics.csv": "label,support,precision,recall,f1\n1.1,10,0.5,0.5,0.5\n",
        "model_snapshot_manifest.json": json.dumps(
            {"model_id": model, "snapshot_sha256": ("1" if model == "esm2_35m" else "2") * 64},
            sort_keys=True,
        )
        + "\n",
        "embedding_manifest.json": json.dumps(
            {"model_id": model, "dtype": "float32", "hidden_size": 8, "pooling": "residue_mean"},
            sort_keys=True,
        )
        + "\n",
        "environment.json": '{"architecture":"arm64","operating_system":"Darwin"}\n',
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
        json.dumps(complete, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_esm_aggregate_writes_exactly_six_sequence_free_files(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix"
    matrix.mkdir()
    for split in ("random", "cluster70", "cluster50", "cluster30"):
        for model in ("esm2_35m", "esm2_150m"):
            _write_cell(matrix, split, model)

    output = tmp_path / "aggregate"
    result = write_esm_validation_aggregates(
        matrix,
        output,
        classical_summary=PROJECT_ROOT / "results/released/v0.3.0/validation_summary.csv",
        expected_classical_sha256=(
            "73ee1c4f8c454a8570058224c9257d4f924eac8c8681fcb78991d99fa6612dc2"
        ),
    )

    assert tuple(path.name for path in result.paths) == (
        "classical_vs_esm_summary.csv",
        "embedding_feature_schema.json",
        "environment_summary.json",
        "esm_validation_per_class.csv",
        "esm_validation_summary.csv",
        "model_snapshot_hashes.json",
    )
    combined = b"".join(path.read_bytes() for path in result.paths)
    assert b"sequence" not in combined.lower()
    assert b"accession" not in combined.lower()
    assert str(tmp_path).encode() not in combined


def test_aggregate_cli_requires_explicit_classical_identity_for_esm() -> None:
    result = CliRunner().invoke(app, ["experiment", "summarize", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "--kind" in output
    assert "--classical-summary" in output
    assert "--classical-sha256" in output
