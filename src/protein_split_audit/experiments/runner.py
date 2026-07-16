# SPDX-License-Identifier: Apache-2.0

"""One-cell Validation experiment runner."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from scipy import sparse  # type: ignore[import-untyped]

from protein_split_audit.config import (
    load_experiment_config,
    load_feature_config,
    load_model_config,
)
from protein_split_audit.evaluation.metrics import (
    EvaluationMetrics,
    PerClassMetrics,
    evaluate_predictions,
)
from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.evaluation.reporting import write_evaluation_report
from protein_split_audit.evaluation.resources import (
    SAMPLING_INTERVAL_SECONDS,
    ResourceUsage,
    measure_call,
)
from protein_split_audit.experiments.provenance import environment_mapping
from protein_split_audit.experiments.schemas import (
    BaselineDefinition,
    ExperimentConfig,
    SplitInput,
)
from protein_split_audit.features.amino_acid_composition import extract_aac
from protein_split_audit.features.cache import FeatureMatrix, get_or_create_feature_cache
from protein_split_audit.features.kmer import extract_kmer3
from protein_split_audit.features.length import extract_length
from protein_split_audit.features.validation import ValidatedInputBundle, load_validation_inputs
from protein_split_audit.models.logistic_regression import TrainedLogistic, train_logistic
from protein_split_audit.models.majority import fit_majority
from protein_split_audit.models.nearest_homolog import (
    HomologHit,
    NearestResult,
    execute_nearest,
    predict_nearest,
)
from protein_split_audit.models.schemas import (
    LogisticRegressionModelConfig,
    MajorityModelConfig,
    NearestHomologModelConfig,
)
from protein_split_audit.models.serialization import save_model
from protein_split_audit.paths import find_project_root
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes, sha256_file

BaselineName = Literal[
    "majority", "length_logistic", "aac_logistic", "kmer3_logistic", "nearest_homolog"
]


@dataclass(frozen=True, slots=True)
class CellResult:
    """One completed Validation matrix cell."""

    split_name: str
    baseline_name: str
    evaluation_split: Literal["validation"]
    run_dir: Path
    metrics: EvaluationMetrics
    manifest_sha256: str


def _write_json(path: Path, mapping: dict[str, object]) -> None:
    path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _run_identity(config_path: Path, split_name: str, baseline_name: str) -> str:
    return sha256_bytes(
        serialize_canonical_json(
            {
                "config_sha256": sha256_file(config_path),
                "split": split_name,
                "baseline": baseline_name,
            }
        )
    )


def _run_id(config_path: Path, split_name: str, baseline_name: str) -> str:
    config = load_experiment_config(config_path)
    if not isinstance(config, ExperimentConfig):
        raise ValueError("v0.3 runner requires a classical experiment configuration")
    identity = _run_identity(config_path, split_name, baseline_name)
    return f"{config.name}__{split_name}__{baseline_name}__seed42__{identity[:12]}"


def _load_metrics(run_dir: Path) -> EvaluationMetrics:
    """Reconstruct metrics only after the completed run has been hash-verified."""

    mapping = json.loads((run_dir / "metrics.json").read_bytes())
    label_order = tuple(str(value) for value in mapping["label_order"])
    with (run_dir / "per_class_metrics.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    per_class = tuple(
        PerClassMetrics(
            label=row["label"],
            support=int(row["support"]),
            precision=float(row["precision"]),
            recall=float(row["recall"]),
            f1=float(row["f1"]),
        )
        for row in rows
    )
    with (run_dir / "confusion_matrix.csv").open(encoding="utf-8", newline="") as stream:
        confusion_rows = list(csv.reader(stream))
    confusion = tuple(tuple(int(value) for value in row[1:]) for row in confusion_rows[1:])
    return EvaluationMetrics(
        label_order=label_order,
        macro_f1=float(mapping["macro_f1"]),
        balanced_accuracy=float(mapping["balanced_accuracy"]),
        accuracy=float(mapping["accuracy"]),
        macro_precision=float(mapping["macro_precision"]),
        macro_recall=float(mapping["macro_recall"]),
        prediction_coverage=float(mapping["prediction_coverage"]),
        per_class=per_class,
        confusion_matrix=confusion,
        no_hit_count=int(mapping["no_hit_count"]),
        no_hit_rate=float(mapping["no_hit_rate"]),
        no_hit_correct_count=int(mapping["no_hit_correct_count"]),
    )


def load_completed_cell(
    config_path: Path,
    split_name: str,
    baseline_name: str,
) -> CellResult:
    """Verify every completed artifact and load one reusable Validation cell."""

    config = load_experiment_config(config_path)
    if not isinstance(config, ExperimentConfig):
        raise ValueError("v0.3 runner requires a classical experiment configuration")
    _select(config_path, split_name, baseline_name)
    identity = _run_identity(config_path, split_name, baseline_name)
    run_dir = config.outputs.root / _run_id(config_path, split_name, baseline_name)
    complete_path = run_dir / "COMPLETE.json"
    try:
        complete = json.loads(complete_path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"completed run is missing a valid COMPLETE.json: {run_dir.name}"
        ) from error
    if (
        complete.get("run_identity") != identity
        or complete.get("split") != split_name
        or complete.get("baseline") != baseline_name
        or complete.get("evaluation_split") != "validation"
    ):
        raise ValueError(f"completed run identity mismatch: {run_dir.name}")
    artifact_hashes = complete.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise ValueError(f"completed run artifact index is invalid: {run_dir.name}")
    current_files = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path != complete_path
    }
    if current_files != set(artifact_hashes):
        raise ValueError(f"completed run artifact set mismatch: {run_dir.name}")
    for relative, expected in sorted(artifact_hashes.items()):
        path = run_dir / relative
        if not isinstance(expected, str) or sha256_file(path) != expected:
            raise ValueError(f"completed run artifact hash mismatch: {run_dir.name}/{relative}")
    metrics = _load_metrics(run_dir)
    return CellResult(
        split_name=split_name,
        baseline_name=baseline_name,
        evaluation_split="validation",
        run_dir=run_dir,
        metrics=metrics,
        manifest_sha256=sha256_file(complete_path),
    )


def _feature_matrix(kind: str, bundle: ValidatedInputBundle) -> FeatureMatrix:
    if kind == "length":
        return extract_length(bundle.records)
    if kind == "aac":
        return extract_aac(bundle.records)
    if kind == "kmer3":
        return extract_kmer3(bundle.records)
    raise ValueError(f"unsupported feature kind: {kind}")


def _write_nearest_rows(path: Path, nearest: NearestResult) -> None:
    rows = tuple(sorted(nearest.rows, key=lambda row: row.query_accession))
    pq.write_table(
        pa.table(
            {
                "query_accession": pa.array(
                    [row.query_accession for row in rows], type=pa.string()
                ),
                "nearest_train_accession": pa.array(
                    [row.nearest_train_accession for row in rows], type=pa.string()
                ),
                "nearest_train_label": pa.array(
                    [row.nearest_train_label for row in rows], type=pa.string()
                ),
                "predicted_label": pa.array(
                    [row.predicted_label for row in rows], type=pa.string()
                ),
                "percent_identity": pa.array(
                    [row.percent_identity for row in rows], type=pa.float64()
                ),
                "query_coverage": pa.array([row.query_coverage for row in rows], type=pa.float64()),
                "target_coverage": pa.array(
                    [row.target_coverage for row in rows], type=pa.float64()
                ),
                "bitscore": pa.array([row.bitscore for row in rows], type=pa.float64()),
                "evalue": pa.array([row.evalue for row in rows], type=pa.float64()),
                "no_hit": pa.array([row.no_hit for row in rows], type=pa.bool_()),
            }
        ),
        path,
    )


def _validation_matrix(matrix: FeatureMatrix, bundle: ValidatedInputBundle) -> FeatureMatrix:
    indices = [index for index, record in enumerate(bundle.records) if record.split == "validation"]
    selected = matrix[indices]
    return sparse.csr_matrix(selected) if sparse.issparse(selected) else np.asarray(selected)


def _prediction_rows(
    bundle: ValidatedInputBundle,
    split_name: str,
    labels: tuple[str, ...],
    scores: np.ndarray,
    *,
    nearest: NearestResult | None = None,
) -> tuple[PredictionRow, ...]:
    validation = tuple(record for record in bundle.records if record.split == "validation")
    if len(validation) != len(labels) or scores.shape != (len(validation), len(bundle.label_order)):
        raise ValueError("prediction output shape disagrees with Validation rows")
    nearest_by_accession = (
        {row.query_accession: row for row in nearest.rows} if nearest is not None else {}
    )
    rows: list[PredictionRow] = []
    for index, record in enumerate(validation):
        nearest_row = nearest_by_accession.get(record.accession)
        rows.append(
            PredictionRow(
                accession=record.accession,
                sequence_sha256=record.sequence_sha256,
                split_name=split_name,
                true_label=record.label,
                predicted_label=labels[index],
                scores=tuple(float(value) for value in scores[index]),
                nearest_train_identity=(
                    nearest_row.percent_identity if nearest_row is not None else None
                ),
                no_hit=nearest_row.no_hit if nearest_row is not None else None,
            )
        )
    return tuple(rows)


def _hard_scores(labels: tuple[str, ...], label_order: tuple[str, ...]) -> np.ndarray:
    return np.asarray(
        [[1.0 if candidate == label else 0.0 for candidate in label_order] for label in labels],
        dtype=np.float64,
    )


def _select(
    config_path: Path, split_name: str, baseline_name: str
) -> tuple[SplitInput, BaselineDefinition]:
    config = load_experiment_config(config_path)
    if not isinstance(config, ExperimentConfig):
        raise ValueError("v0.3 runner requires a classical experiment configuration")
    if config.evaluation.split != "validation":
        raise ValueError("v0.3 experiment runner is Validation-only")
    split = next((item for item in config.splits if item.name == split_name), None)
    baseline = next((item for item in config.baselines if item.name == baseline_name), None)
    if split is None or baseline is None:
        raise ValueError("unknown split or baseline")
    return split, baseline


def run_experiment_cell(
    config_path: Path,
    split_name: str,
    baseline_name: str,
    *,
    nearest_hits: tuple[HomologHit, ...] | None = None,
    resume: bool = False,
) -> CellResult:
    """Run one frozen Validation cell and atomically publish its local artifacts."""

    config = load_experiment_config(config_path)
    if not isinstance(config, ExperimentConfig):
        raise ValueError("v0.3 runner requires a classical experiment configuration")
    split, baseline = _select(config_path, split_name, baseline_name)
    run_identity = _run_identity(config_path, split_name, baseline_name)
    run_id = _run_id(config_path, split_name, baseline_name)
    run_dir = config.outputs.root / run_id
    if run_dir.exists():
        if resume:
            return load_completed_cell(config_path, split_name, baseline_name)
        raise FileExistsError(f"completed run already exists: {run_id}")
    stage = config.outputs.root / f".{run_id}.staging"
    if stage.exists():
        raise FileExistsError(f"staging run already exists: {run_id}")

    bundle = load_validation_inputs(
        cohort_manifest=config.cohort.manifest,
        cohort_content_manifest=config.cohort.content_manifest,
        cohort_fasta=config.cohort.fasta,
        split_manifest=split.manifest,
        split_content_manifest=split.content_manifest,
    )
    validation_records = tuple(record for record in bundle.records if record.split == "validation")
    model_config = load_model_config(baseline.model_path)
    feature_manifest: Path | None = None
    trained: TrainedLogistic | None = None
    nearest: NearestResult | None = None
    training_usage = ResourceUsage(0.0, 0, SAMPLING_INTERVAL_SECONDS)

    if isinstance(model_config, MajorityModelConfig):
        majority, training_usage = measure_call(
            lambda: fit_majority([row.label for row in bundle.records if row.split == "train"])
        )
        labels, prediction_usage = measure_call(lambda: majority.predict(len(validation_records)))
        scores = _hard_scores(labels, bundle.label_order)
    elif isinstance(model_config, LogisticRegressionModelConfig):
        if baseline.feature_path is None:
            raise ValueError("Logistic Regression baseline requires a feature configuration")
        feature_config = load_feature_config(baseline.feature_path)
        raw_matrix = _feature_matrix(feature_config.kind, bundle)
        project_root = find_project_root(config_path) or config.outputs.root.parent
        cached = get_or_create_feature_cache(
            project_root / "cache/features", feature_config, bundle, raw_matrix
        )
        feature_manifest = cached.directory / "manifest.json"
        trained_model, training_usage = measure_call(
            lambda: train_logistic(
                cached.matrix, bundle.records, bundle.label_order, feature_config, model_config
            )
        )
        trained = trained_model
        evaluation_matrix = _validation_matrix(cached.matrix, bundle)
        result, prediction_usage = measure_call(
            lambda: (
                trained_model.predict(evaluation_matrix),
                trained_model.predict_proba(evaluation_matrix),
            )
        )
        labels, scores = result
    elif isinstance(model_config, NearestHomologModelConfig):
        if nearest_hits is None:
            (nearest, mmseqs_run), prediction_usage = measure_call(
                lambda: execute_nearest(bundle.records, model_config)
            )
            mmseqs_metadata: dict[str, object] = {
                "command": list(mmseqs_run.sanitized_argv),
                "exit_code": mmseqs_run.returncode,
                "mmseqs_version": mmseqs_run.mmseqs_version,
                "threads": model_config.runtime.threads,
            }
        else:
            nearest, prediction_usage = measure_call(
                lambda: predict_nearest(bundle.records, nearest_hits)
            )
            mmseqs_metadata = {"mocked": True, "threads": 1}
        if nearest is None:
            raise AssertionError("nearest-homolog execution returned no predictions")
        labels = tuple(row.predicted_label for row in nearest.rows)
        scores = _hard_scores(labels, bundle.label_order)
    else:
        raise AssertionError("unreachable model configuration")

    rows = _prediction_rows(bundle, split_name, labels, np.asarray(scores), nearest=nearest)
    metrics = evaluate_predictions(rows, bundle.label_order)
    write_evaluation_report(stage, rows, metrics)
    if nearest is not None:
        _write_nearest_rows(stage / "nearest_homolog.parquet", nearest)
    if trained is not None:
        save_model(stage / "model.joblib", trained)
    if feature_manifest is not None:
        (stage / "feature_manifest.json").write_bytes(feature_manifest.read_bytes())
    (stage / "config_resolved.yaml").write_bytes(config_path.read_bytes())
    _write_json(
        stage / "input_manifests.json",
        {
            "cohort_content_manifest_sha256": bundle.cohort_content_manifest_sha256,
            "cohort_fasta_sha256": bundle.cohort_fasta_sha256,
            "cohort_manifest_sha256": bundle.cohort_manifest_sha256,
            "split_content_manifest_sha256": bundle.split_content_manifest_sha256,
            "split_manifest_sha256": bundle.split_manifest_sha256,
        },
    )
    model_mapping: dict[str, object] = {
        "baseline": baseline_name,
        "label_order": list(bundle.label_order),
        "model_config_sha256": sha256_file(baseline.model_path),
        "score_semantics": "probability" if trained is not None else "hard_prediction",
        "train_count": sum(row.split == "train" for row in bundle.records),
    }
    if isinstance(model_config, NearestHomologModelConfig):
        model_mapping["mmseqs"] = mmseqs_metadata
    _write_json(stage / "model_manifest.json", model_mapping)
    _write_json(
        stage / "resource_usage.json",
        {
            "prediction_time_seconds": prediction_usage.elapsed_seconds,
            "training_time_seconds": training_usage.elapsed_seconds,
            "peak_rss_bytes": max(training_usage.peak_rss_bytes, prediction_usage.peak_rss_bytes),
            "sampling_interval_seconds": prediction_usage.sampling_interval_seconds,
        },
    )
    _write_json(stage / "environment.json", environment_mapping(config_path))
    (stage / "run.log").write_text(
        f"split={split_name}\nbaseline={baseline_name}\nevaluation_split=validation\nstatus=complete\n",
        encoding="utf-8",
        newline="\n",
    )
    artifacts = {
        path.relative_to(stage).as_posix(): sha256_file(path)
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    }
    _write_json(
        stage / "COMPLETE.json",
        {
            "artifact_sha256": artifacts,
            "baseline": baseline_name,
            "evaluation_split": "validation",
            "run_identity": run_identity,
            "split": split_name,
        },
    )
    config.outputs.root.mkdir(parents=True, exist_ok=True)
    os.replace(stage, run_dir)
    return CellResult(
        split_name=split_name,
        baseline_name=baseline_name,
        evaluation_split="validation",
        run_dir=run_dir,
        metrics=metrics,
        manifest_sha256=sha256_file(run_dir / "COMPLETE.json"),
    )


__all__ = ["CellResult", "load_completed_cell", "run_experiment_cell"]
