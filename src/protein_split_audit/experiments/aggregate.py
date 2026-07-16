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

_SAFE_ENVIRONMENT_FIELDS = frozenset(
    {
        "architecture",
        "dependencies",
        "device",
        "dtype",
        "git_commit",
        "git_dirty",
        "machine_model",
        "operating_system",
        "operating_system_version",
        "python_version",
        "software_version",
        "torch_deterministic_algorithms",
        "torch_interop_threads",
        "torch_intraop_threads",
        "uv_lock_sha256",
        "version_info",
    }
)


@dataclass(frozen=True, slots=True)
class ValidationAggregateResult:
    """Sequence-free aggregate Validation files."""

    output_dir: Path
    summary_path: Path
    paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class EsmValidationAggregateResult:
    """Six reviewed, aggregate-only v0.4 preview files."""

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


def _verify_esm_cell(cell: Path) -> tuple[dict[str, object], dict[str, object]]:
    complete = json.loads((cell / "COMPLETE.json").read_bytes())
    if (
        complete.get("evaluation_split") != "validation"
        or complete.get("test_sequence_count_processed") != 0
        or complete.get("test_labels_accessed") != 0
        or complete.get("test_metrics_generated") != 0
    ):
        raise ValueError("ESM aggregate encountered a non-Validation or Test-accessing cell")
    hashes = complete.get("artifact_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("ESM cell artifact index is invalid")
    current = {
        path.relative_to(cell).as_posix()
        for path in cell.rglob("*")
        if path.is_file() and path.name != "COMPLETE.json"
    }
    if current != set(hashes):
        raise ValueError("ESM cell artifact set mismatch")
    for relative, expected in hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("ESM cell artifact index is invalid")
        if sha256_file(cell / relative) != expected:
            raise ValueError(f"ESM cell artifact hash mismatch: {relative}")
    metrics = json.loads((cell / "metrics.json").read_bytes())
    if any("test" in str(key).lower() for key in metrics):
        raise ValueError("ESM aggregate metrics contain forbidden Test fields")
    return complete, metrics


def _safe_environment(environment_path: Path) -> dict[str, object]:
    environment = json.loads(environment_path.read_bytes())
    if not isinstance(environment, dict):
        raise ValueError("ESM environment identity must be a mapping")
    unexpected = sorted(set(environment) - _SAFE_ENVIRONMENT_FIELDS)
    if unexpected:
        raise ValueError(f"ESM aggregate has unapproved environment fields: {unexpected}")
    encoded = json.dumps(environment, ensure_ascii=False, sort_keys=True)
    if any(marker in encoded.lower() for marker in ("secret", "password", "token=")):
        raise ValueError("ESM aggregate environment contains a possible secret")
    return environment


def write_esm_validation_aggregates(
    matrix_dir: Path,
    output_dir: Path,
    *,
    classical_summary: Path,
    expected_classical_sha256: str,
) -> EsmValidationAggregateResult:
    """Verify eight ESM cells and write six deterministic sequence-free previews."""

    if output_dir.exists():
        raise FileExistsError(f"ESM aggregate output already exists: {output_dir.name}")
    if sha256_file(classical_summary) != expected_classical_sha256:
        raise ValueError("released v0.3 classical summary hash mismatch")
    cells = sorted(path for path in matrix_dir.iterdir() if (path / "COMPLETE.json").is_file())
    if len(cells) != 8:
        raise ValueError("ESM Validation aggregate requires exactly eight completed cells")
    summary_rows: list[dict[str, object]] = []
    per_class_rows: list[dict[str, object]] = []
    schemas: dict[str, dict[str, object]] = {}
    snapshots: dict[str, dict[str, object]] = {}
    environments: dict[str, dict[str, object]] = {}
    identities: set[tuple[str, str]] = set()
    for cell in cells:
        complete, metrics = _verify_esm_cell(cell)
        split = str(complete["split"])
        model = str(complete["model"])
        identities.add((split, model))
        summary_rows.append(
            {
                "split": split,
                "model": model,
                **{
                    key: metrics[key]
                    for key in (
                        "accuracy",
                        "balanced_accuracy",
                        "macro_f1",
                        "macro_precision",
                        "macro_recall",
                        "prediction_coverage",
                    )
                },
            }
        )
        with (cell / "per_class_metrics.csv").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                per_class_rows.append({"split": split, "model": model, **row})
        embedding = json.loads((cell / "embedding_manifest.json").read_bytes())
        schemas[model] = {
            "dtype": embedding.get("dtype"),
            "hidden_size": embedding.get("hidden_size"),
            "model_id": model,
            "pooling": embedding.get("pooling", "residue_mean"),
        }
        snapshot = json.loads((cell / "model_snapshot_manifest.json").read_bytes())
        snapshots[model] = {
            "model_id": model,
            "snapshot_sha256": snapshot["snapshot_sha256"],
        }
        environment_path = cell / "environment.json"
        environment = _safe_environment(environment_path)
        environments[sha256_file(environment_path)] = environment
    expected = {
        (split, model)
        for split in ("random", "cluster70", "cluster50", "cluster30")
        for model in ("esm2_35m", "esm2_150m")
    }
    if identities != expected:
        raise ValueError("ESM aggregate cells do not match the frozen eight-cell matrix")

    output_dir.mkdir(parents=True)
    summary_rows.sort(key=lambda row: (str(row["split"]), str(row["model"])))
    summary_columns = [
        "split",
        "model",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "macro_precision",
        "macro_recall",
        "prediction_coverage",
    ]
    summary_path = output_dir / "esm_validation_summary.csv"
    _write_csv(
        summary_path,
        [summary_columns] + [[row[column] for column in summary_columns] for row in summary_rows],
    )
    per_class_rows.sort(key=lambda row: (str(row["split"]), str(row["model"]), str(row["label"])))
    per_class_columns = ["split", "model", "label", "support", "precision", "recall", "f1"]
    per_class_path = output_dir / "esm_validation_per_class.csv"
    _write_csv(
        per_class_path,
        [per_class_columns]
        + [[row[column] for column in per_class_columns] for row in per_class_rows],
    )

    comparison_path = output_dir / "classical_vs_esm_summary.csv"
    with classical_summary.open(encoding="utf-8", newline="") as stream:
        classical_rows = list(csv.DictReader(stream))
    comparison_columns = [
        "release_source",
        "split",
        "method",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "macro_precision",
        "macro_recall",
        "prediction_coverage",
    ]
    comparison_rows: list[list[object]] = []
    for row in classical_rows:
        comparison_rows.append(
            ["v0.3.0", row["split"], row["baseline"]]
            + [row[column] for column in comparison_columns[3:]]
        )
    for row in summary_rows:
        comparison_rows.append(
            ["v0.4.0", row["split"], row["model"]]
            + [row[column] for column in comparison_columns[3:]]
        )
    comparison_rows.sort(key=lambda row: (str(row[1]), str(row[2]), str(row[0])))
    _write_csv(comparison_path, [comparison_columns, *comparison_rows])

    schema_path = output_dir / "embedding_feature_schema.json"
    snapshot_path = output_dir / "model_snapshot_hashes.json"
    environment_path = output_dir / "environment_summary.json"
    _write_json(schema_path, {"models": [schemas[key] for key in sorted(schemas)]})
    _write_json(snapshot_path, {"models": [snapshots[key] for key in sorted(snapshots)]})
    _write_json(
        environment_path,
        {
            "cell_count": 8,
            "environment_count": len(environments),
            "environments": [environments[key] for key in sorted(environments)],
        },
    )
    paths = tuple(sorted(output_dir.iterdir(), key=lambda path: path.name))
    if len(paths) != 6:
        raise AssertionError("ESM aggregate writer produced an unexpected file count")
    return EsmValidationAggregateResult(output_dir, summary_path, paths)


__all__ = [
    "EsmValidationAggregateResult",
    "ValidationAggregateResult",
    "write_esm_validation_aggregates",
    "write_validation_aggregates",
]
