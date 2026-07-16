# SPDX-License-Identifier: Apache-2.0

"""Deterministic two-model by four-split ESM Validation matrix."""

from __future__ import annotations

import csv
import json
import os
import platform
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt

from protein_split_audit.config import (
    load_embedding_config,
    load_experiment_config,
    load_model_config,
)
from protein_split_audit.embeddings.cache import (
    load_embedding_cache,
    write_embedding_cache,
)
from protein_split_audit.embeddings.extract import extract_embedding_matrix
from protein_split_audit.embeddings.model_registry import (
    load_local_esm_model,
    verify_model_snapshot,
)
from protein_split_audit.embeddings.provenance import (
    load_snapshot_manifest,
    snapshot_manifest_path,
)
from protein_split_audit.evaluation.metrics import (
    EvaluationMetrics,
    PerClassMetrics,
    evaluate_predictions,
)
from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.evaluation.reporting import write_evaluation_report
from protein_split_audit.experiments.provenance import environment_mapping
from protein_split_audit.experiments.schemas import (
    EsmExperimentConfig,
    EsmModelDefinition,
    SplitInput,
)
from protein_split_audit.features.validation import (
    SequenceRecord,
    ValidatedInputBundle,
    load_feature_inputs,
    load_validation_inputs,
)
from protein_split_audit.models.esm_linear_probe import (
    save_esm_linear_probe,
    train_esm_linear_probe,
)
from protein_split_audit.models.schemas import EsmLinearProbeConfig
from protein_split_audit.paths import find_project_root
from protein_split_audit.provenance import (
    git_metadata,
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)


@dataclass(frozen=True, slots=True)
class EsmCellResult:
    """One completed ESM Validation cell."""

    split_name: str
    model_name: str
    evaluation_split: Literal["validation"]
    run_dir: Path
    metrics: EvaluationMetrics
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class EsmMatrixResult:
    """One complete eight-cell ESM Validation matrix."""

    cells: tuple[EsmCellResult, ...]
    summary_path: Path


@dataclass(frozen=True, slots=True)
class PreparedEmbeddings:
    """Verified embeddings and the manifests copied into a local run."""

    matrix: npt.NDArray[np.float32]
    embedding_manifest: dict[str, object]
    embedding_manifest_sha256: str
    snapshot_manifest: dict[str, object]
    cache_directory: Path | None = None


EsmCellRunner = Callable[..., EsmCellResult]
EmbeddingProvider = Callable[..., PreparedEmbeddings]


def _json_bytes(mapping: dict[str, object]) -> bytes:
    return (json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _dependency_versions() -> dict[str, str]:
    dependencies = {
        name: version(distribution)
        for name, distribution in (
            ("safetensors", "safetensors"),
            ("tokenizers", "tokenizers"),
            ("torch", "torch"),
            ("transformers", "transformers"),
        )
    }
    dependencies["python"] = platform.python_version()
    return dependencies


def _default_embedding_provider(
    *,
    config_path: Path,
    experiment: EsmExperimentConfig,
    model: EsmModelDefinition,
    split: SplitInput,
    records: tuple[SequenceRecord, ...],
    bundle: ValidatedInputBundle,
) -> PreparedEmbeddings:
    """Load a verified local snapshot and create/reuse its immutable cache."""

    del records
    project_root = find_project_root(config_path)
    if project_root is None:
        raise ValueError("project root not found for ESM extraction")
    git = git_metadata(project_root)
    if git.dirty is not False:
        raise ValueError("formal model access requires a clean Git working tree")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("formal model access requires Darwin/arm64")
    embedding_config = load_embedding_config(model.embedding_config)
    if embedding_config.model_id != model.name:
        raise ValueError("experiment model name disagrees with embedding configuration")
    manifest = load_snapshot_manifest(snapshot_manifest_path(project_root, model.name))
    verify_model_snapshot(embedding_config, manifest)

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        embedding_config.model.snapshot_root,
        local_files_only=True,
        revision=embedding_config.model.tokenizer_revision,
    )
    loaded = load_local_esm_model(
        embedding_config.model.snapshot_root,
        device=experiment.runtime.device,
        intraop_threads=experiment.runtime.torch_intraop_threads,
        interop_threads=experiment.runtime.torch_interop_threads,
        deterministic_algorithms=experiment.runtime.deterministic_algorithms,
    )
    extracted = extract_embedding_matrix(
        bundle.records,
        tokenizer,
        loaded.encoder,
        max_padded_tokens=embedding_config.batching.max_padded_tokens,
        device=experiment.runtime.device,
    )
    dependencies = _dependency_versions()
    try:
        cache = write_embedding_cache(
            embedding_config,
            manifest,
            bundle,
            matrix=extracted.matrix,
            batching=extracted.batching,
            loading_info=loaded.loading_info,
            split_name=split.name,
            dependency_versions=dependencies,
        )
    except FileExistsError:
        from protein_split_audit.embeddings.cache import embedding_cache_key

        key = embedding_cache_key(embedding_config, manifest, bundle, split.name, dependencies)
        cache = load_embedding_cache(
            embedding_config.cache.root / embedding_config.model_id / key,
            embedding_config,
            manifest,
            bundle,
            split_name=split.name,
            dependency_versions=dependencies,
        )
    manifest_mapping = cache.manifest.model_dump(mode="json")
    return PreparedEmbeddings(
        matrix=cache.matrix,
        embedding_manifest=manifest_mapping,
        embedding_manifest_sha256=sha256_bytes(serialize_canonical_json(manifest_mapping)),
        snapshot_manifest=manifest.model_dump(mode="json"),
        cache_directory=cache.directory,
    )


def _select(
    experiment: EsmExperimentConfig,
    model_name: str,
    split_name: str,
) -> tuple[EsmModelDefinition, SplitInput]:
    model = next((item for item in experiment.models if item.name == model_name), None)
    split = next((item for item in experiment.splits if item.name == split_name), None)
    if model is None or split is None:
        raise ValueError("unknown v0.4 model or split")
    return model, split


def _run_identity(config_path: Path, model_name: str, split_name: str) -> str:
    return sha256_bytes(
        serialize_canonical_json(
            {
                "config_sha256": sha256_file(config_path),
                "model": model_name,
                "split": split_name,
            }
        )
    )


def _load_completed_esm_cell(
    run_dir: Path,
    *,
    identity: str,
    model_name: str,
    split_name: str,
) -> EsmCellResult:
    """Verify every completed artifact before reusing a v0.4 cell."""

    complete_path = run_dir / "COMPLETE.json"
    try:
        complete = json.loads(complete_path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("completed ESM run has no valid COMPLETE.json") from error
    if (
        complete.get("run_identity") != identity
        or complete.get("model") != model_name
        or complete.get("split") != split_name
        or complete.get("evaluation_split") != "validation"
        or complete.get("test_sequence_count_processed") != 0
        or complete.get("test_labels_accessed") != 0
        or complete.get("test_metrics_generated") != 0
    ):
        raise ValueError("completed ESM run identity mismatch")
    artifact_hashes = complete.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise ValueError("completed ESM run artifact index is invalid")
    current = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path != complete_path
    }
    if current != set(artifact_hashes):
        raise ValueError("completed ESM run artifact set mismatch")
    for relative, expected in sorted(artifact_hashes.items()):
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("completed ESM run artifact index is invalid")
        if sha256_file(run_dir / relative) != expected:
            raise ValueError(f"completed ESM artifact hash mismatch: {relative}")

    metrics_mapping = json.loads((run_dir / "metrics.json").read_bytes())
    label_order = tuple(str(value) for value in metrics_mapping["label_order"])
    with (run_dir / "per_class_metrics.csv").open(encoding="utf-8", newline="") as stream:
        per_class_rows = list(csv.DictReader(stream))
    per_class = tuple(
        PerClassMetrics(
            row["label"],
            int(row["support"]),
            float(row["precision"]),
            float(row["recall"]),
            float(row["f1"]),
        )
        for row in per_class_rows
    )
    with (run_dir / "confusion_matrix.csv").open(encoding="utf-8", newline="") as stream:
        confusion_rows = list(csv.reader(stream))
    confusion = tuple(tuple(int(value) for value in row[1:]) for row in confusion_rows[1:])
    metrics = EvaluationMetrics(
        label_order=label_order,
        macro_f1=float(metrics_mapping["macro_f1"]),
        balanced_accuracy=float(metrics_mapping["balanced_accuracy"]),
        accuracy=float(metrics_mapping["accuracy"]),
        macro_precision=float(metrics_mapping["macro_precision"]),
        macro_recall=float(metrics_mapping["macro_recall"]),
        prediction_coverage=float(metrics_mapping["prediction_coverage"]),
        per_class=per_class,
        confusion_matrix=confusion,
        no_hit_count=int(metrics_mapping["no_hit_count"]),
        no_hit_rate=float(metrics_mapping["no_hit_rate"]),
        no_hit_correct_count=int(metrics_mapping["no_hit_correct_count"]),
    )
    return EsmCellResult(
        split_name,
        model_name,
        "validation",
        run_dir,
        metrics,
        sha256_file(complete_path),
    )


def prepare_embeddings(
    config_path: Path,
    model_name: str,
    split_name: str,
) -> PreparedEmbeddings:
    """Prepare one verified Train/Validation cache without opening labels."""

    experiment = load_experiment_config(config_path)
    if (
        not isinstance(experiment, EsmExperimentConfig)
        or experiment.evaluation.split != "validation"
    ):
        raise ValueError("v0.4 embedding extraction requires a Validation configuration")
    model, split = _select(experiment, model_name, split_name)
    bundle = load_feature_inputs(
        cohort_manifest=experiment.cohort.manifest,
        cohort_content_manifest=experiment.cohort.content_manifest,
        cohort_fasta=experiment.cohort.fasta,
        split_manifest=split.manifest,
        split_content_manifest=split.content_manifest,
    )
    return _default_embedding_provider(
        config_path=config_path,
        experiment=experiment,
        model=model,
        split=split,
        records=bundle.records,
        bundle=bundle,
    )


def run_esm_cell(
    config_path: Path,
    model_name: str,
    split_name: str,
    *,
    resume: bool = False,
    embedding_provider: EmbeddingProvider = _default_embedding_provider,
) -> EsmCellResult:
    """Run one frozen ESM Train-to-Validation cell."""

    experiment = load_experiment_config(config_path)
    if (
        not isinstance(experiment, EsmExperimentConfig)
        or experiment.evaluation.split != "validation"
    ):
        raise ValueError("v0.4 ESM cell requires a Validation configuration")
    model, split = _select(experiment, model_name, split_name)
    identity = _run_identity(config_path, model_name, split_name)
    run_id = f"{experiment.name}__{split_name}__{model_name}__seed42__{identity[:12]}"
    run_dir = experiment.outputs.root / run_id
    if run_dir.exists():
        if resume:
            return _load_completed_esm_cell(
                run_dir,
                identity=identity,
                model_name=model_name,
                split_name=split_name,
            )
        raise FileExistsError(f"completed ESM run already exists: {run_id}")
    stage = experiment.outputs.root / f".{run_id}.staging"
    if stage.exists():
        raise FileExistsError(f"staging ESM run already exists: {run_id}")

    feature_bundle = load_feature_inputs(
        cohort_manifest=experiment.cohort.manifest,
        cohort_content_manifest=experiment.cohort.content_manifest,
        cohort_fasta=experiment.cohort.fasta,
        split_manifest=split.manifest,
        split_content_manifest=split.content_manifest,
    )
    prepared = embedding_provider(
        config_path=config_path,
        experiment=experiment,
        model=model,
        split=split,
        records=feature_bundle.records,
        bundle=feature_bundle,
    )
    label_bundle = load_validation_inputs(
        cohort_manifest=experiment.cohort.manifest,
        cohort_content_manifest=experiment.cohort.content_manifest,
        cohort_fasta=experiment.cohort.fasta,
        split_manifest=split.manifest,
        split_content_manifest=split.content_manifest,
    )
    feature_identity = tuple(
        (record.accession, record.sequence_sha256, record.split)
        for record in feature_bundle.records
    )
    label_identity = tuple(
        (record.accession, record.sequence_sha256, record.split) for record in label_bundle.records
    )
    if feature_identity != label_identity:
        raise ValueError("feature and label input identities disagree")
    if prepared.matrix.shape[0] != len(label_bundle.records):
        raise ValueError("embedding rows disagree with validated inputs")
    probe_config = load_model_config(experiment.linear_probe_config)
    if not isinstance(probe_config, EsmLinearProbeConfig):
        raise ValueError("v0.4 experiment requires the ESM Linear Probe configuration")
    trained = train_esm_linear_probe(
        prepared.matrix,
        label_bundle.records,
        label_bundle.label_order,
        probe_config,
        embedding_manifest_sha256=prepared.embedding_manifest_sha256,
    )
    validation_indices = [
        index for index, record in enumerate(label_bundle.records) if record.split == "validation"
    ]
    validation_matrix = np.asarray(prepared.matrix[validation_indices], dtype=np.float32)
    labels = trained.predict(validation_matrix)
    scores = trained.predict_proba(validation_matrix)
    validation_records = [label_bundle.records[index] for index in validation_indices]
    rows = tuple(
        PredictionRow(
            accession=record.accession,
            sequence_sha256=record.sequence_sha256,
            split_name=split_name,
            true_label=record.label,
            predicted_label=labels[index],
            scores=tuple(float(value) for value in scores[index]),
            nearest_train_identity=None,
            no_hit=None,
        )
        for index, record in enumerate(validation_records)
    )
    metrics = evaluate_predictions(rows, label_bundle.label_order)
    write_evaluation_report(stage, rows, metrics)
    save_esm_linear_probe(stage / "model.joblib", trained)
    (stage / "config_resolved.yaml").write_bytes(config_path.read_bytes())
    (stage / "embedding_manifest.json").write_bytes(_json_bytes(prepared.embedding_manifest))
    (stage / "model_snapshot_manifest.json").write_bytes(_json_bytes(prepared.snapshot_manifest))
    (stage / "input_manifests.json").write_bytes(
        _json_bytes(
            {
                "cohort_content_manifest_sha256": label_bundle.cohort_content_manifest_sha256,
                "cohort_fasta_sha256": label_bundle.cohort_fasta_sha256,
                "cohort_manifest_sha256": label_bundle.cohort_manifest_sha256,
                "requested_partitions": ["train", "validation"],
                "split_content_manifest_sha256": label_bundle.split_content_manifest_sha256,
                "split_manifest_sha256": label_bundle.split_manifest_sha256,
                "test_labels_accessed": 0,
                "test_metrics_generated": 0,
                "test_sequence_count_processed": 0,
            }
        )
    )
    scaler = trained.scaler.state
    (stage / "scaler_manifest.json").write_bytes(
        _json_bytes(
            {
                "embedding_manifest_sha256": scaler.embedding_manifest_sha256,
                "feature_count": scaler.feature_count,
                "mean": scaler.mean.tolist(),
                "scale": scaler.scale.tolist(),
                "train_accession_sha256": scaler.train_accession_sha256,
                "train_count": scaler.train_count,
                "train_row_index_sha256": scaler.train_row_index_sha256,
            }
        )
    )
    (stage / "classifier_manifest.json").write_bytes(
        _json_bytes(
            {
                "C": probe_config.c,
                "class_weight": probe_config.class_weight,
                "fit_intercept": probe_config.fit_intercept,
                "label_order": list(label_bundle.label_order),
                "max_iter": probe_config.max_iter,
                "penalty": probe_config.penalty,
                "random_state": probe_config.random_state,
                "solver": probe_config.solver,
                "tol": probe_config.tol,
                "train_count": len(trained.train_accessions),
            }
        )
    )
    (stage / "environment.json").write_bytes(
        _json_bytes(
            environment_mapping(
                config_path,
                runtime={
                    "device": experiment.runtime.device,
                    "dtype": experiment.runtime.dtype,
                    "torch_deterministic_algorithms": (experiment.runtime.deterministic_algorithms),
                    "torch_interop_threads": experiment.runtime.torch_interop_threads,
                    "torch_intraop_threads": experiment.runtime.torch_intraop_threads,
                },
            )
        )
    )
    (stage / "resource_usage.json").write_bytes(_json_bytes({"formal_measurement_pending": True}))
    (stage / "run.log").write_text(
        f"split={split_name}\nmodel={model_name}\nevaluation_split=validation\nstatus=complete\n",
        encoding="utf-8",
        newline="\n",
    )
    artifacts = {
        path.relative_to(stage).as_posix(): sha256_file(path)
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    }
    (stage / "COMPLETE.json").write_bytes(
        _json_bytes(
            {
                "artifact_sha256": artifacts,
                "evaluation_split": "validation",
                "model": model_name,
                "run_identity": identity,
                "split": split_name,
                "test_labels_accessed": 0,
                "test_metrics_generated": 0,
                "test_sequence_count_processed": 0,
            }
        )
    )
    experiment.outputs.root.mkdir(parents=True, exist_ok=True)
    os.replace(stage, run_dir)
    return EsmCellResult(
        split_name,
        model_name,
        "validation",
        run_dir,
        metrics,
        sha256_file(run_dir / "COMPLETE.json"),
    )


def run_esm_matrix(
    config_path: Path,
    *,
    resume: bool = False,
    cell_runner: EsmCellRunner = run_esm_cell,
) -> EsmMatrixResult:
    """Run exactly eight cells in frozen split/model order."""

    config = load_experiment_config(config_path)
    if not isinstance(config, EsmExperimentConfig) or config.evaluation.split != "validation":
        raise ValueError("v0.4 ESM matrix requires a Validation configuration")
    summary_path = config.outputs.root / "matrix_summary.json"
    if summary_path.exists() and not resume:
        raise FileExistsError("completed ESM Validation matrix already exists")
    cells = tuple(
        cell_runner(config_path, model.name, split.name, resume=resume)
        for split in config.splits
        for model in config.models
    )
    if len(cells) != 8 or len({(cell.model_name, cell.split_name) for cell in cells}) != 8:
        raise ValueError("ESM Validation matrix must contain eight unique cells")
    payload = {
        "cell_count": 8,
        "evaluation_split": "validation",
        "models": [model.name for model in config.models],
        "splits": [split.name for split in config.splits],
        "cells": [
            {
                "balanced_accuracy": cell.metrics.balanced_accuracy,
                "macro_f1": cell.metrics.macro_f1,
                "model": cell.model_name,
                "split": cell.split_name,
            }
            for cell in cells
        ],
        "test_labels_accessed": 0,
        "test_metrics_generated": 0,
        "test_sequence_count_processed": 0,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if summary_path.exists():
        if summary_path.read_text(encoding="utf-8") != rendered:
            raise ValueError("completed ESM Validation matrix summary mismatch")
    else:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(rendered, encoding="utf-8", newline="\n")
    return EsmMatrixResult(cells, summary_path)


__all__ = [
    "EsmCellResult",
    "EsmMatrixResult",
    "PreparedEmbeddings",
    "prepare_embeddings",
    "run_esm_cell",
    "run_esm_matrix",
]
