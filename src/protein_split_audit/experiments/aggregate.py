# SPDX-License-Identifier: Apache-2.0

"""Aggregate-only Validation matrix publication preview."""

from __future__ import annotations

import csv
import io
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.evaluation.standalone import verify_evaluation_run
from protein_split_audit.features.kmer import KMER3_VOCABULARY
from protein_split_audit.provenance import sha256_bytes, sha256_file


@dataclass(frozen=True, slots=True)
class ValidationAggregateResult:
    """Sequence-free aggregate Validation files."""

    output_dir: Path
    summary_path: Path
    paths: tuple[Path, ...]


def _write_csv(path: Path, rows: Sequence[Sequence[object]]) -> None:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    path.write_text(stream.getvalue(), encoding="utf-8", newline="\n")


def _write_json(path: Path, mapping: dict[str, object]) -> None:
    path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _identity_summary(cell: Path) -> dict[str, float | int | None]:
    nearest_path = cell / "nearest_homolog.parquet"
    if not nearest_path.is_file():
        return {
            "hit_count": None,
            "identity_min": None,
            "identity_median": None,
            "identity_mean": None,
            "identity_p90": None,
            "identity_p95": None,
            "identity_max": None,
        }
    values = sorted(
        float(value)
        for value in pq.read_table(nearest_path, columns=["percent_identity"])
        .column("percent_identity")
        .to_pylist()
        if value is not None
    )
    if not values:
        return {
            "hit_count": 0,
            "identity_min": None,
            "identity_median": None,
            "identity_mean": None,
            "identity_p90": None,
            "identity_p95": None,
            "identity_max": None,
        }
    return {
        "hit_count": len(values),
        "identity_min": min(values),
        "identity_median": statistics.median(values),
        "identity_mean": statistics.fmean(values),
        "identity_p90": float(np.percentile(values, 90)),
        "identity_p95": float(np.percentile(values, 95)),
        "identity_max": max(values),
    }


def write_validation_aggregates(
    matrix_dir: Path,
    output_dir: Path,
) -> ValidationAggregateResult:
    """Verify 20 cells and write deterministic aggregate-only summaries."""

    if output_dir.exists():
        raise FileExistsError(f"aggregate output already exists: {output_dir.name}")
    cells = sorted(path for path in matrix_dir.iterdir() if (path / "COMPLETE.json").is_file())
    if len(cells) != 20:
        raise ValueError("Validation aggregate requires exactly 20 completed cells")
    summary_rows: list[dict[str, object]] = []
    per_class_rows: list[dict[str, object]] = []
    feature_schemas: dict[str, object] = {}
    environments: dict[str, dict[str, object]] = {}
    for cell in cells:
        verify_evaluation_run(cell)
        complete = json.loads((cell / "COMPLETE.json").read_bytes())
        metrics = json.loads((cell / "metrics.json").read_bytes())
        split = str(complete["split"])
        baseline = str(complete["baseline"])
        identity = _identity_summary(cell)
        summary_rows.append(
            {
                "split": split,
                "baseline": baseline,
                **{
                    key: metrics[key]
                    for key in (
                        "accuracy",
                        "balanced_accuracy",
                        "macro_f1",
                        "macro_precision",
                        "macro_recall",
                        "prediction_coverage",
                        "no_hit_count",
                        "no_hit_rate",
                        "no_hit_correct_count",
                    )
                },
                **identity,
            }
        )
        with (cell / "per_class_metrics.csv").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                per_class_rows.append({"split": split, "baseline": baseline, **row})
        feature_path = cell / "feature_manifest.json"
        if feature_path.is_file():
            feature = json.loads(feature_path.read_bytes())["identity"]["feature"]
            feature_schemas[str(feature["name"])] = feature
        environment_path = cell / "environment.json"
        environment = json.loads(environment_path.read_bytes())
        environments[sha256_file(environment_path)] = environment
    output_dir.mkdir(parents=True)
    summary_rows.sort(key=lambda row: (str(row["split"]), str(row["baseline"])))
    summary_columns = [
        "split",
        "baseline",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "macro_precision",
        "macro_recall",
        "prediction_coverage",
        "no_hit_count",
        "no_hit_rate",
        "no_hit_correct_count",
        "hit_count",
        "identity_min",
        "identity_median",
        "identity_mean",
        "identity_p90",
        "identity_p95",
        "identity_max",
    ]
    summary_path = output_dir / "validation_summary.csv"
    _write_csv(
        summary_path,
        [summary_columns] + [[row[column] for column in summary_columns] for row in summary_rows],
    )
    per_class_rows.sort(
        key=lambda row: (str(row["split"]), str(row["baseline"]), str(row["label"]))
    )
    per_class_columns = ["split", "baseline", "label", "support", "precision", "recall", "f1"]
    per_class_path = output_dir / "validation_per_class.csv"
    _write_csv(
        per_class_path,
        [per_class_columns]
        + [[row[column] for column in per_class_columns] for row in per_class_rows],
    )
    feature_path = output_dir / "feature_schema.json"
    _write_json(
        feature_path,
        {
            "features": [feature_schemas[name] for name in sorted(feature_schemas)],
            "kmer3_vocabulary_sha256": sha256_bytes(
                ("\n".join(KMER3_VOCABULARY) + "\n").encode("ascii")
            ),
        },
    )
    environment_path = output_dir / "environment_summary.json"
    _write_json(
        environment_path,
        {
            "cell_count": len(cells),
            "environment_count": len(environments),
            "environments": [environments[key] for key in sorted(environments)],
        },
    )
    paths = (summary_path, per_class_path, feature_path, environment_path)
    return ValidationAggregateResult(output_dir, summary_path, paths)


__all__ = ["ValidationAggregateResult", "write_validation_aggregates"]
