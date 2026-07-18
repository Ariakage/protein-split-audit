# SPDX-License-Identifier: Apache-2.0

"""Frozen seven-method by four-split Test matrix orchestration."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from scipy import sparse  # type: ignore[import-untyped]

from protein_split_audit.attestations.test_access import (
    VerifiedTestAuthorization,
    begin_test_session,
    complete_test_session,
    require_verified_authorization,
    verify_test_authorization,
    write_test_incident,
)
from protein_split_audit.config import (
    load_embedding_config,
    load_experiment_config,
    load_feature_config,
    load_model_config,
)
from protein_split_audit.embeddings.extract import extract_frozen_test_embedding_matrix
from protein_split_audit.embeddings.model_registry import (
    load_local_esm_model,
    verify_model_snapshot,
)
from protein_split_audit.embeddings.provenance import load_snapshot_manifest
from protein_split_audit.evaluation.generalization_gap import generalization_gap
from protein_split_audit.evaluation.metrics import EvaluationMetrics, evaluate_predictions
from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.evaluation.reporting import write_evaluation_report
from protein_split_audit.evaluation.resources import (
    SAMPLING_INTERVAL_SECONDS,
    ResourceUsage,
    measure_call,
)
from protein_split_audit.evaluation.test_aggregate import (
    TestAggregateResult,
    write_test_aggregates,
)
from protein_split_audit.evaluation.test_inputs import (
    FrozenTestBundle,
    load_frozen_test_bundle,
    load_test_labels_after_predictions,
)
from protein_split_audit.experiments.provenance import environment_mapping
from protein_split_audit.experiments.replay import TestReplayReport, compare_test_replays
from protein_split_audit.experiments.schemas import (
    FrozenMethodName,
    FrozenSplitName,
    FrozenTestExperimentConfig,
    FrozenTestMethodDefinition,
    FrozenTestSplitInput,
)
from protein_split_audit.features.amino_acid_composition import extract_aac
from protein_split_audit.features.cache import FeatureMatrix, feature_matrix_sha256
from protein_split_audit.features.kmer import extract_kmer3
from protein_split_audit.features.length import extract_length
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.esm_linear_probe import (
    save_esm_linear_probe,
    train_esm_linear_probe,
)
from protein_split_audit.models.logistic_regression import train_logistic
from protein_split_audit.models.majority import fit_majority
from protein_split_audit.models.nearest_homolog import (
    HomologHit,
    NearestResult,
    execute_test_nearest,
    predict_test_nearest,
)
from protein_split_audit.models.schemas import (
    EsmLinearProbeConfig,
    LogisticRegressionModelConfig,
    MajorityModelConfig,
    NearestHomologModelConfig,
)
from protein_split_audit.models.serialization import save_model
from protein_split_audit.paths import find_project_root
from protein_split_audit.provenance import (
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.statistics.confidence_intervals import metric_confidence_interval
from protein_split_audit.statistics.paired_comparison import paired_metric_comparison

_METHOD_ORDER = (
    "majority",
    "length_logistic",
    "aac_logistic",
    "kmer3_logistic",
    "nearest_homolog",
    "esm2_35m",
    "esm2_150m",
)
_SPLIT_ORDER = ("random", "cluster70", "cluster50", "cluster30")
SessionName = Literal["run-a", "run-b"]


@dataclass(frozen=True, slots=True)
class FrozenTestCell:
    """One exact method/split identity in protocol order."""

    cell_id: str
    method_name: FrozenMethodName
    split_name: FrozenSplitName
    method: FrozenTestMethodDefinition
    split: FrozenTestSplitInput


def _method_slug(name: str) -> str:
    return name.replace("_", "-")


def frozen_test_cells(config: FrozenTestExperimentConfig) -> tuple[FrozenTestCell, ...]:
    """Return the exact stable 28-cell Cartesian product or reject drift."""

    methods = tuple(item.name for item in config.methods)
    splits = tuple(item.name for item in config.splits)
    if methods != _METHOD_ORDER:
        raise ValueError("v0.5 frozen Test method order or membership changed")
    if splits != _SPLIT_ORDER:
        raise ValueError("v0.5 frozen Test split order or membership changed")
    cells = tuple(
        FrozenTestCell(
            cell_id=f"v050-test__{_method_slug(method.name)}__{split.name}",
            method_name=method.name,
            split_name=split.name,
            method=method,
            split=split,
        )
        for method in config.methods
        for split in config.splits
    )
    if len(cells) != 28 or len({item.cell_id for item in cells}) != 28:
        raise ValueError("v0.5 frozen Test matrix must contain 28 unique cells")
    return cells


def records_with_train_labels(bundle: FrozenTestBundle) -> tuple[SequenceRecord, ...]:
    """Adapt records for frozen primitives without materializing any Test target."""

    records = tuple(
        SequenceRecord(
            accession=record.accession,
            sequence_sha256=record.sequence_sha256,
            label=bundle.train_labels[record.accession] if record.partition == "train" else "",
            split=record.partition,
            sequence=record.sequence,
        )
        for record in bundle.records
    )
    if any(record.split == "validation" for record in records):
        raise ValueError("Validation records are forbidden in the frozen Test matrix")
    if any(
        (record.split == "train") != (record.accession in bundle.train_labels) for record in records
    ):
        raise ValueError("Train label mapping differs from the frozen Train partition")
    if any(record.label for record in records if record.split == "test"):
        raise ValueError("Test labels must remain unavailable during fit and prediction")
    return records


def select_test_matrix_rows(
    matrix: FeatureMatrix,
    records: tuple[SequenceRecord, ...],
) -> FeatureMatrix:
    """Select Test rows for transform/predict only, preserving matrix type."""

    if matrix.shape[0] != len(records):
        raise ValueError("matrix row count disagrees with frozen records")
    indices = [index for index, record in enumerate(records) if record.split == "test"]
    if not indices:
        raise ValueError("frozen Test matrix has no Test rows")
    selected = matrix[indices]
    if sparse.issparse(selected):
        return sparse.csr_matrix(selected, dtype=np.float64)
    return np.asarray(selected)


@dataclass(frozen=True, slots=True)
class UnlabeledTestPrediction:
    """One sealed prediction before its Test target is opened."""

    accession: str
    sequence_sha256: bytes
    predicted_label: str
    scores: tuple[float, ...]
    nearest_train_identity: float | None = None
    no_hit: bool | None = None


@dataclass(frozen=True, slots=True)
class PreparedTestPredictions:
    """Predictions plus local run-specific resource observations."""

    rows: tuple[UnlabeledTestPrediction, ...]
    training_usage: ResourceUsage
    prediction_usage: ResourceUsage
    nearest: NearestResult | None = None


@dataclass(frozen=True, slots=True)
class TestCellResult:
    """One atomically completed formal Test cell."""

    cell_id: str
    method_name: FrozenMethodName
    split_name: FrozenSplitName
    run_dir: Path
    metrics: EvaluationMetrics
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class TestSessionResult:
    """One complete 28-cell formal session."""

    session: SessionName
    cells: tuple[TestCellResult, ...]
    root: Path
    summary_path: Path
    summary_sha256: str


@dataclass(frozen=True, slots=True)
class FrozenTestProtocolResult:
    """Two consecutive formal Test sessions and their replay-gated review aggregate."""

    run_a: TestSessionResult
    run_b: TestSessionResult
    replay: TestReplayReport
    aggregate: TestAggregateResult


BundleLoader = Callable[
    [FrozenTestExperimentConfig, FrozenSplitName, VerifiedTestAuthorization], FrozenTestBundle
]
CellRunner = Callable[
    [
        Path,
        FrozenTestExperimentConfig,
        FrozenTestCell,
        FrozenTestBundle,
        VerifiedTestAuthorization,
        SessionName,
    ],
    TestCellResult,
]
StatisticsWriter = Callable[
    [
        tuple[TestCellResult, ...],
        Mapping[FrozenSplitName, FrozenTestBundle],
        FrozenTestExperimentConfig,
        Path,
    ],
    Path,
]


def _write_json(path: Path, mapping: Mapping[str, object]) -> Path:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(mapping), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _without_session_namespace(identity: Mapping[str, object]) -> dict[str, object]:
    """Return the deterministic identity shared by both formal replay sessions."""

    return {str(key): value for key, value in identity.items() if str(key) != "session"}


def _hard_scores(
    labels: tuple[str, ...],
    label_order: tuple[str, ...],
) -> npt.NDArray[np.float64]:
    return np.asarray(
        [[1.0 if candidate == label else 0.0 for candidate in label_order] for label in labels],
        dtype=np.float64,
    )


def _extract_feature_matrix(kind: str, records: tuple[SequenceRecord, ...]) -> FeatureMatrix:
    if kind == "length":
        return extract_length(records)
    if kind == "aac":
        return extract_aac(records)
    if kind == "kmer3":
        return extract_kmer3(records)
    raise ValueError(f"unsupported frozen feature kind: {kind}")


def _write_feature_artifacts(
    stage: Path,
    matrix: FeatureMatrix,
    records: tuple[SequenceRecord, ...],
    *,
    method: FrozenTestMethodDefinition,
    bundle: FrozenTestBundle,
    authorization: VerifiedTestAuthorization,
    session: SessionName,
) -> None:
    feature_dir = stage / "feature_cache"
    feature_dir.mkdir()
    storage: str
    files: list[str]
    if sparse.isspmatrix_csr(matrix):
        canonical = sparse.csr_matrix(matrix, dtype=np.float64)
        canonical.sort_indices()
        np.save(feature_dir / "data.npy", canonical.data, allow_pickle=False)
        np.save(feature_dir / "indices.npy", canonical.indices, allow_pickle=False)
        np.save(feature_dir / "indptr.npy", canonical.indptr, allow_pickle=False)
        storage = "csr"
        files = ["data.npy", "indices.npy", "indptr.npy"]
    else:
        np.save(
            feature_dir / "matrix.npy",
            np.ascontiguousarray(matrix, dtype=np.float64),
            allow_pickle=False,
        )
        storage = "dense"
        files = ["matrix.npy"]
    pq.write_table(
        pa.table(
            {
                "row_index": pa.array(range(len(records)), type=pa.uint32()),
                "accession": pa.array([row.accession for row in records], type=pa.string()),
                "sequence_sha256": pa.array(
                    [row.sequence_sha256 for row in records], type=pa.binary(32)
                ),
                "partition": pa.array([row.split for row in records], type=pa.string()),
            }
        ),
        feature_dir / "index.parquet",
        compression="zstd",
        use_dictionary=False,
    )
    identity: dict[str, object] = {
        "attestation_sha256": authorization.attestation_sha256,
        "execution_commit": authorization.execution_commit,
        "feature_config_sha256": (
            sha256_file(method.feature_config) if method.feature_config is not None else None
        ),
        "implementation_version": "frozen-test-feature-v1-r1",
        "input_hashes": dict(bundle.input_hashes),
        "method": method.name,
        "partitions": ["train", "test"],
        "session": session,
        "split": bundle.split_name,
    }
    _write_json(
        feature_dir / "manifest.json",
        {
            "cache_key": sha256_bytes(
                serialize_canonical_json(_without_session_namespace(identity))
            ),
            "column_count": int(matrix.shape[1]),
            "files": files,
            "identity": identity,
            "matrix_semantic_sha256": feature_matrix_sha256(matrix),
            "row_count": int(matrix.shape[0]),
            "storage": storage,
        },
    )


def _float32_matrix_hash(matrix: npt.NDArray[np.float32]) -> str:
    contiguous = np.ascontiguousarray(matrix, dtype="<f4")
    header = serialize_canonical_json(
        {"dtype": "float32", "shape": list(contiguous.shape), "storage": "dense"}
    )
    return sha256_bytes(header + contiguous.tobytes(order="C"))


def _write_embedding_artifacts(
    stage: Path,
    matrix: npt.NDArray[np.float32],
    records: tuple[SequenceRecord, ...],
    *,
    method: FrozenTestMethodDefinition,
    bundle: FrozenTestBundle,
    authorization: VerifiedTestAuthorization,
    session: SessionName,
    batching: Mapping[str, object],
    loading_info: Mapping[str, list[object]],
) -> str:
    embedding_dir = stage / "embedding_cache"
    embedding_dir.mkdir()
    matrix_path = embedding_dir / "embeddings.npy"
    np.save(matrix_path, np.ascontiguousarray(matrix), allow_pickle=False)
    pq.write_table(
        pa.table(
            {
                "row_index": pa.array(range(len(records)), type=pa.uint32()),
                "accession": pa.array([row.accession for row in records], type=pa.string()),
                "sequence_sha256": pa.array(
                    [row.sequence_sha256 for row in records], type=pa.binary(32)
                ),
                "partition": pa.array([row.split for row in records], type=pa.string()),
                "model": pa.array([method.name] * len(records), type=pa.string()),
            }
        ),
        embedding_dir / "index.parquet",
        compression="zstd",
        use_dictionary=False,
    )
    normalized_loading = {
        key: [str(value) for value in loading_info.get(key, [])]
        for key in ("error_msgs", "mismatched_keys", "missing_keys", "unexpected_keys")
    }
    if any(normalized_loading.values()):
        raise ValueError("formal ESM loading information must be empty")
    identity: dict[str, object] = {
        "attestation_sha256": authorization.attestation_sha256,
        "embedding_config_sha256": (
            sha256_file(method.embedding_config) if method.embedding_config is not None else None
        ),
        "execution_commit": authorization.execution_commit,
        "implementation_version": "frozen-test-esm-residue-mean-v1-r1",
        "input_hashes": dict(bundle.input_hashes),
        "method": method.name,
        "partitions": ["train", "test"],
        "session": session,
        "split": bundle.split_name,
    }
    manifest: dict[str, object] = {
        "batching": dict(batching),
        "cache_key": sha256_bytes(serialize_canonical_json(_without_session_namespace(identity))),
        "identity": identity,
        "loading_info": normalized_loading,
        "matrix_file_sha256": sha256_file(matrix_path),
        "matrix_semantic_sha256": _float32_matrix_hash(matrix),
        "row_count": int(matrix.shape[0]),
        "hidden_size": int(matrix.shape[1]),
    }
    deterministic_manifest = dict(manifest)
    deterministic_manifest["identity"] = _without_session_namespace(identity)
    deterministic_manifest_sha256 = sha256_bytes(serialize_canonical_json(deterministic_manifest))
    manifest["deterministic_manifest_sha256"] = deterministic_manifest_sha256
    _write_json(embedding_dir / "manifest.json", manifest)
    return deterministic_manifest_sha256


def _test_records(bundle: FrozenTestBundle) -> tuple[SequenceRecord, ...]:
    return tuple(record for record in records_with_train_labels(bundle) if record.split == "test")


def _prepared_rows(
    test_records: tuple[SequenceRecord, ...],
    labels: tuple[str, ...],
    scores: npt.NDArray[np.float64],
    label_order: tuple[str, ...],
    *,
    nearest: NearestResult | None = None,
) -> tuple[UnlabeledTestPrediction, ...]:
    if len(labels) != len(test_records) or scores.shape != (
        len(test_records),
        len(label_order),
    ):
        raise ValueError("prediction output shape disagrees with frozen Test rows")
    nearest_by_accession = (
        {row.query_accession: row for row in nearest.rows} if nearest is not None else {}
    )
    rows = tuple(
        UnlabeledTestPrediction(
            accession=record.accession,
            sequence_sha256=record.sequence_sha256,
            predicted_label=labels[index],
            scores=tuple(float(value) for value in scores[index]),
            nearest_train_identity=(
                nearest_by_accession[record.accession].percent_identity
                if record.accession in nearest_by_accession
                else None
            ),
            no_hit=(
                nearest_by_accession[record.accession].no_hit
                if record.accession in nearest_by_accession
                else None
            ),
        )
        for index, record in enumerate(test_records)
    )
    if any(row.predicted_label not in label_order for row in rows):
        raise ValueError("prediction contains a label outside the frozen order")
    return rows


def _execute_default_method(
    stage: Path,
    config: FrozenTestExperimentConfig,
    cell: FrozenTestCell,
    bundle: FrozenTestBundle,
    authorization: VerifiedTestAuthorization,
    session: SessionName,
    *,
    nearest_hits: tuple[HomologHit, ...] | None = None,
) -> PreparedTestPredictions:
    records = records_with_train_labels(bundle)
    test_records = _test_records(bundle)
    model_config = load_model_config(cell.method.model_config_path)
    zero_usage = ResourceUsage(0.0, 0, SAMPLING_INTERVAL_SECONDS)
    nearest: NearestResult | None = None

    if isinstance(model_config, MajorityModelConfig):
        majority, training_usage = measure_call(
            lambda: fit_majority([record.label for record in records if record.split == "train"])
        )
        labels, prediction_usage = measure_call(lambda: majority.predict(len(test_records)))
        scores = _hard_scores(labels, bundle.label_order)
        _write_json(
            stage / "model_manifest.json",
            {
                "counts": [list(item) for item in majority.counts],
                "fit_partitions": ["train"],
                "model": cell.method.name,
                "prediction_partitions": ["test"],
            },
        )
    elif isinstance(model_config, LogisticRegressionModelConfig):
        if cell.method.feature_config is None:
            raise ValueError("frozen Logistic method is missing its feature configuration")
        feature_config = load_feature_config(cell.method.feature_config)
        matrix = _extract_feature_matrix(feature_config.kind, records)
        _write_feature_artifacts(
            stage,
            matrix,
            records,
            method=cell.method,
            bundle=bundle,
            authorization=authorization,
            session=session,
        )
        logistic_trained, training_usage = measure_call(
            lambda: train_logistic(
                matrix,
                records,
                bundle.label_order,
                feature_config,
                model_config,
            )
        )
        test_matrix = select_test_matrix_rows(matrix, records)
        result, prediction_usage = measure_call(
            lambda: (
                logistic_trained.predict(test_matrix),
                logistic_trained.predict_proba(test_matrix),
            )
        )
        labels, scores = result
        save_model(stage / "model.joblib", logistic_trained)
        estimator = logistic_trained.estimator
        scaler = estimator.named_steps.get("scaler")
        _write_json(
            stage / "model_manifest.json",
            {
                "classifier": estimator.named_steps["classifier"].get_params(),
                "fit_partitions": ["train"],
                "label_order": list(bundle.label_order),
                "model": cell.method.name,
                "prediction_partitions": ["test"],
                "scaler_mean": (
                    np.asarray(scaler.mean_, dtype=np.float64).tolist()
                    if scaler is not None
                    else None
                ),
                "scaler_scale": (
                    np.asarray(scaler.scale_, dtype=np.float64).tolist()
                    if scaler is not None
                    else None
                ),
                "train_accession_sha256": sha256_bytes(
                    serialize_canonical_json(
                        {"accessions": list(logistic_trained.train_accessions)}
                    )
                ),
            },
        )
    elif isinstance(model_config, NearestHomologModelConfig):
        if nearest_hits is None:
            (nearest, mmseqs), prediction_usage = measure_call(
                lambda: execute_test_nearest(records, model_config, authorization)
            )
            mmseqs_mapping: dict[str, object] = {
                "command": list(mmseqs.sanitized_argv),
                "exit_code": mmseqs.returncode,
                "version": mmseqs.mmseqs_version,
            }
        else:
            nearest, prediction_usage = measure_call(
                lambda: predict_test_nearest(records, nearest_hits, authorization)
            )
            mmseqs_mapping = {"mocked": True}
        if nearest is None:
            raise AssertionError("nearest-homolog execution returned no predictions")
        training_usage = zero_usage
        labels = tuple(row.predicted_label for row in nearest.rows)
        scores = _hard_scores(labels, bundle.label_order)
        _write_json(
            stage / "model_manifest.json",
            {
                "fit_partitions": ["train"],
                "mmseqs": mmseqs_mapping,
                "model": cell.method.name,
                "prediction_partitions": ["test"],
            },
        )
    elif isinstance(model_config, EsmLinearProbeConfig):
        if cell.method.embedding_config is None:
            raise ValueError("frozen ESM method is missing its embedding configuration")
        embedding_config = load_embedding_config(cell.method.embedding_config)
        identity = next(item for item in config.model_snapshots if item.name == cell.method.name)
        snapshot = load_snapshot_manifest(identity.manifest)
        verify_model_snapshot(embedding_config, snapshot)
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            embedding_config.model.snapshot_root,
            local_files_only=True,
            revision=embedding_config.model.tokenizer_revision,
        )
        loaded = load_local_esm_model(
            embedding_config.model.snapshot_root,
            device=config.runtime.device,
            intraop_threads=config.runtime.torch_intraop_threads,
            interop_threads=config.runtime.torch_interop_threads,
            deterministic_algorithms=config.runtime.deterministic_algorithms,
        )
        extracted, extraction_usage = measure_call(
            lambda: extract_frozen_test_embedding_matrix(
                records,
                tokenizer,
                loaded.encoder,
                authorization,
                max_padded_tokens=embedding_config.batching.max_padded_tokens,
                device=config.runtime.device,
            )
        )
        embedding_manifest_sha256 = _write_embedding_artifacts(
            stage,
            extracted.matrix,
            records,
            method=cell.method,
            bundle=bundle,
            authorization=authorization,
            session=session,
            batching=asdict(extracted.batching),
            loading_info=loaded.loading_info,
        )
        esm_trained, fitting_usage = measure_call(
            lambda: train_esm_linear_probe(
                extracted.matrix,
                records,
                bundle.label_order,
                model_config,
                embedding_manifest_sha256=embedding_manifest_sha256,
            )
        )
        training_usage = ResourceUsage(
            extraction_usage.elapsed_seconds + fitting_usage.elapsed_seconds,
            max(extraction_usage.peak_rss_bytes, fitting_usage.peak_rss_bytes),
            SAMPLING_INTERVAL_SECONDS,
        )
        test_matrix = cast(
            npt.NDArray[np.float32],
            np.asarray(select_test_matrix_rows(extracted.matrix, records), dtype=np.float32),
        )
        result, prediction_usage = measure_call(
            lambda: (
                esm_trained.predict(test_matrix),
                esm_trained.predict_proba(test_matrix),
            )
        )
        labels, scores = result
        save_esm_linear_probe(stage / "model.joblib", esm_trained)
        _write_json(
            stage / "model_manifest.json",
            {
                "classifier": esm_trained.classifier.get_params(),
                "fit_partitions": ["train"],
                "label_order": list(bundle.label_order),
                "model": cell.method.name,
                "prediction_partitions": ["test"],
                "scaler_mean": esm_trained.scaler.state.mean.tolist(),
                "scaler_scale": esm_trained.scaler.state.scale.tolist(),
                "snapshot_sha256": snapshot.snapshot_sha256,
                "train_accession_sha256": (esm_trained.scaler.state.train_accession_sha256),
            },
        )
    else:
        raise ValueError("frozen Test method has an unsupported model configuration")

    return PreparedTestPredictions(
        rows=_prepared_rows(
            test_records,
            labels,
            np.asarray(scores, dtype=np.float64),
            bundle.label_order,
            nearest=nearest,
        ),
        training_usage=training_usage,
        prediction_usage=prediction_usage,
        nearest=nearest,
    )


def _write_unlabeled_predictions(
    stage: Path,
    prepared: PreparedTestPredictions,
    label_order: tuple[str, ...],
) -> Path:
    score_columns = {
        f"score_{label.replace('.', '_')}": pa.array(
            [row.scores[index] for row in prepared.rows], type=pa.float64()
        )
        for index, label in enumerate(label_order)
    }
    path = stage / "predictions_unlabeled.parquet"
    pq.write_table(
        pa.table(
            {
                "accession": pa.array([row.accession for row in prepared.rows], type=pa.string()),
                "sequence_sha256": pa.array(
                    [row.sequence_sha256 for row in prepared.rows], type=pa.binary(32)
                ),
                "predicted_label": pa.array(
                    [row.predicted_label for row in prepared.rows], type=pa.string()
                ),
                **score_columns,
                "nearest_train_identity": pa.array(
                    [row.nearest_train_identity for row in prepared.rows],
                    type=pa.float64(),
                ),
                "no_hit": pa.array([row.no_hit for row in prepared.rows], type=pa.bool_()),
            }
        ),
        path,
        compression="zstd",
        use_dictionary=False,
    )
    return path


def _write_prediction_manifest(
    stage: Path,
    cell: FrozenTestCell,
    prepared: PreparedTestPredictions,
    artifact: Path,
) -> Path:
    return _write_json(
        stage / "prediction_manifest.json",
        {
            "contains_true_labels": False,
            "evaluation_partition": "test",
            "inventory": [
                {
                    "accession": row.accession,
                    "sequence_sha256": row.sequence_sha256.hex(),
                }
                for row in prepared.rows
            ],
            "manifest_schema_version": 1,
            "method": cell.method_name,
            "prediction_artifact": artifact.name,
            "prediction_artifact_sha256": sha256_file(artifact),
            "row_count": len(prepared.rows),
            "split_name": cell.split_name,
            "status": "complete",
        },
    )


def _write_nearest_detail(stage: Path, nearest: NearestResult) -> None:
    rows = tuple(sorted(nearest.rows, key=lambda item: item.query_accession))
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
        stage / "nearest_homolog.parquet",
        compression="zstd",
        use_dictionary=False,
    )


def _publish_evaluation_report(
    stage: Path,
    rows: tuple[PredictionRow, ...],
    metrics: EvaluationMetrics,
) -> None:
    temporary = stage / ".evaluation"
    artifacts = write_evaluation_report(temporary, rows, metrics)
    for source in artifacts.values():
        os.replace(source, stage / source.name)
    temporary.rmdir()


def _run_test_cell(
    config_path: Path,
    config: FrozenTestExperimentConfig,
    cell: FrozenTestCell,
    bundle: FrozenTestBundle,
    authorization: VerifiedTestAuthorization,
    session: SessionName,
) -> TestCellResult:
    require_verified_authorization(authorization)
    session_root = config.outputs.root / session
    run_dir = session_root / cell.cell_id
    stage = session_root / f".{cell.cell_id}.staging"
    if run_dir.exists() or stage.exists():
        raise FileExistsError(f"formal Test cell already exists: {cell.cell_id}")
    stage.mkdir(parents=True)
    try:
        prepared = _execute_default_method(
            stage,
            config,
            cell,
            bundle,
            authorization,
            session,
        )
        expected_inventory = tuple(
            (record.accession, record.sequence_sha256)
            for record in bundle.records
            if record.partition == "test"
        )
        observed_inventory = tuple((row.accession, row.sequence_sha256) for row in prepared.rows)
        if observed_inventory != expected_inventory:
            raise ValueError("unlabeled predictions differ from the frozen Test inventory")
        unlabeled = _write_unlabeled_predictions(stage, prepared, bundle.label_order)
        prediction_manifest = _write_prediction_manifest(
            stage,
            cell,
            prepared,
            unlabeled,
        )
        test_labels = load_test_labels_after_predictions(
            bundle,
            prediction_manifest,
            authorization,
        )
        rows = tuple(
            PredictionRow(
                accession=row.accession,
                sequence_sha256=row.sequence_sha256,
                split_name=cell.split_name,
                true_label=test_labels[row.accession],
                predicted_label=row.predicted_label,
                scores=row.scores,
                nearest_train_identity=row.nearest_train_identity,
                no_hit=row.no_hit,
                evaluation_split="test",
            )
            for row in prepared.rows
        )
        metrics = evaluate_predictions(rows, bundle.label_order)
        components = {
            record.accession: record.bootstrap_component_id
            for record in bundle.records
            if record.partition == "test"
        }
        interval_rows = [
            metric_confidence_interval(
                tuple(row.true_label for row in rows),
                tuple(row.predicted_label for row in rows),
                tuple(components[row.accession] for row in rows),
                bundle.label_order,
                config.statistics.bootstrap,
                metric=metric,
                domain=f"cell:{cell.split_name}:{metric}:{cell.method_name}",
            ).model_dump(mode="json")
            for metric in config.statistics.primary_metrics
        ]
        _write_json(
            stage / "confidence_intervals.json",
            {"intervals": interval_rows, "method": cell.method_name, "split": cell.split_name},
        )
        _publish_evaluation_report(stage, rows, metrics)
        if prepared.nearest is not None:
            _write_nearest_detail(stage, prepared.nearest)
        (stage / "config_resolved.yaml").write_bytes(config_path.read_bytes())
        _write_json(stage / "input_hashes.json", dict(bundle.input_hashes))
        _write_json(
            stage / "environment.json",
            {
                **environment_mapping(
                    config_path,
                    runtime={
                        "device": config.runtime.device,
                        "dtype": config.runtime.dtype,
                        "mmseqs_threads": config.runtime.mmseqs_threads,
                        "mmseqs_version": config.runtime.mmseqs_version,
                        "torch_deterministic_algorithms": (config.runtime.deterministic_algorithms),
                        "torch_interop_threads": config.runtime.torch_interop_threads,
                        "torch_intraop_threads": config.runtime.torch_intraop_threads,
                    },
                ),
                "attestation_sha256": authorization.attestation_sha256,
                "execution_commit": authorization.execution_commit,
            },
        )
        _write_json(
            stage / "resource_usage.json",
            {
                "deterministic_content": False,
                "peak_rss_bytes": max(
                    prepared.training_usage.peak_rss_bytes,
                    prepared.prediction_usage.peak_rss_bytes,
                ),
                "prediction_time_seconds": prepared.prediction_usage.elapsed_seconds,
                "sampling_interval_seconds": SAMPLING_INTERVAL_SECONDS,
                "training_time_seconds": prepared.training_usage.elapsed_seconds,
            },
        )
        (stage / "run.log").write_text(
            f"session={session}\ncell={cell.cell_id}\nevaluation_split=test\nstatus=complete\n",
            encoding="utf-8",
            newline="\n",
        )
        artifacts = {
            path.relative_to(stage).as_posix(): sha256_file(path)
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        complete = _write_json(
            stage / "COMPLETE.json",
            {
                "artifact_sha256": artifacts,
                "attestation_sha256": authorization.attestation_sha256,
                "cell_id": cell.cell_id,
                "evaluation_split": "test",
                "execution_commit": authorization.execution_commit,
                "fit_partitions": ["train"],
                "method": cell.method_name,
                "prediction_partitions": ["test"],
                "session": session,
                "split": cell.split_name,
                "test_labels_accessed": 66,
                "test_metrics_generated": 1,
                "test_sequence_count_processed": 66,
                "validation_rows_accessed": 0,
            },
        )
        os.replace(stage, run_dir)
        return TestCellResult(
            cell_id=cell.cell_id,
            method_name=cell.method_name,
            split_name=cell.split_name,
            run_dir=run_dir,
            metrics=metrics,
            manifest_sha256=sha256_file(run_dir / complete.name),
        )
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _load_completed_predictions(
    result: TestCellResult,
    label_order: tuple[str, ...],
) -> tuple[PredictionRow, ...]:
    table = pq.read_table(result.run_dir / "predictions.parquet")
    rows = table.to_pylist()
    loaded = tuple(
        PredictionRow(
            accession=str(row["accession"]),
            sequence_sha256=bytes(row["sequence_sha256"]),
            split_name=str(row["split_name"]),
            true_label=str(row["true_label"]),
            predicted_label=str(row["predicted_label"]),
            scores=tuple(float(row[f"score_{label.replace('.', '_')}"]) for label in label_order),
            nearest_train_identity=(
                float(row["nearest_train_identity"])
                if row["nearest_train_identity"] is not None
                else None
            ),
            no_hit=bool(row["no_hit"]) if row["no_hit"] is not None else None,
            evaluation_split="test",
        )
        for row in rows
    )
    if len(loaded) != 66 or tuple(row.accession for row in loaded) != tuple(
        sorted(row.accession for row in loaded)
    ):
        raise ValueError("completed Test predictions must contain 66 canonical rows")
    return loaded


def _write_session_statistics(
    results: tuple[TestCellResult, ...],
    bundles: Mapping[FrozenSplitName, FrozenTestBundle],
    config: FrozenTestExperimentConfig,
    session_root: Path,
) -> Path:
    by_identity = {(item.method_name, item.split_name): item for item in results}
    predictions = {
        identity: _load_completed_predictions(result, config.evaluation.label_order)
        for identity, result in by_identity.items()
    }
    components = {
        split: tuple(
            record.bootstrap_component_id for record in bundle.records if record.partition == "test"
        )
        for split, bundle in bundles.items()
    }
    paired_rows: list[dict[str, object]] = []
    for split_name in _SPLIT_ORDER:
        split = cast(FrozenSplitName, split_name)
        for comparison in config.statistics.method_comparisons:
            for metric in config.statistics.primary_metrics:
                paired_rows.append(
                    paired_metric_comparison(
                        predictions[(comparison.method_a, split)],
                        predictions[(comparison.method_b, split)],
                        components[split],
                        config.evaluation.label_order,
                        config.statistics.bootstrap,
                        split_name=split,
                        metric=metric,
                        method_a=comparison.method_a,
                        method_b=comparison.method_b,
                    ).model_dump(mode="json")
                )
    gap_rows: list[dict[str, object]] = []
    for method_name in _METHOD_ORDER:
        method = cast(FrozenMethodName, method_name)
        for comparison_split in config.statistics.generalization_comparison_splits:
            gap_rows.append(
                generalization_gap(
                    predictions[(method, "random")],
                    predictions[(method, comparison_split)],
                    components["random"],
                    components[comparison_split],
                    config.evaluation.label_order,
                    config.statistics.bootstrap,
                    method=method,
                    comparison_split=comparison_split,
                ).model_dump(mode="json")
            )
    interval_hashes = {
        result.cell_id: sha256_file(result.run_dir / "confidence_intervals.json")
        for result in results
    }
    return _write_json(
        session_root / "statistics.json",
        {
            "cell_interval_sha256": interval_hashes,
            "generalization_gaps": gap_rows,
            "method_comparisons": paired_rows,
            "statistics_identity": config.statistics.model_dump(mode="json"),
        },
    )


def _run_test_session_from_config(
    config_path: Path,
    config: FrozenTestExperimentConfig,
    session: SessionName,
    authorization: VerifiedTestAuthorization,
    *,
    bundle_loader: BundleLoader,
    cell_runner: CellRunner,
    statistics_writer: StatisticsWriter,
) -> TestSessionResult:
    require_verified_authorization(authorization)
    if session not in authorization.allowed_sessions:
        raise ValueError(f"formal Test session is not authorized: {session}")
    cells = frozen_test_cells(config)
    session_root = config.outputs.root / session
    if session_root.exists():
        raise FileExistsError(f"formal Test session already exists: {session}")

    bundles: dict[FrozenSplitName, FrozenTestBundle] = {}
    ledger_root = config.outputs.root / "access-ledger"
    consumed = False

    def first_test_read() -> None:
        nonlocal consumed
        consumed = True
        bundles["random"] = bundle_loader(config, "random", authorization)

    try:
        begin_test_session(
            authorization,
            session,
            ledger_root,
            before_test_read=first_test_read,
        )
        for split_name in _SPLIT_ORDER[1:]:
            typed_split = cast(FrozenSplitName, split_name)
            bundles[typed_split] = bundle_loader(config, typed_split, authorization)
        results = tuple(
            cell_runner(
                config_path,
                config,
                cell,
                bundles[cell.split_name],
                authorization,
                session,
            )
            for cell in cells
        )
        if len(results) != 28 or tuple(item.cell_id for item in results) != tuple(
            item.cell_id for item in cells
        ):
            raise ValueError("formal Test session did not complete the exact matrix")
        statistics_path = statistics_writer(
            results,
            bundles,
            config,
            session_root,
        )
        summary = _write_json(
            session_root / "matrix_summary.json",
            {
                "attestation_sha256": authorization.attestation_sha256,
                "cell_count": 28,
                "cells": [
                    {
                        "balanced_accuracy": item.metrics.balanced_accuracy,
                        "cell_id": item.cell_id,
                        "macro_f1": item.metrics.macro_f1,
                        "manifest_sha256": item.manifest_sha256,
                        "method": item.method_name,
                        "split": item.split_name,
                    }
                    for item in results
                ],
                "evaluation_split": "test",
                "execution_commit": authorization.execution_commit,
                "session": session,
                "statistics_sha256": sha256_file(statistics_path),
                "validation_rows_accessed": 0,
            },
        )
        summary_sha256 = sha256_file(summary)
        complete_test_session(
            authorization,
            session,
            ledger_root,
            summary_sha256,
        )
        return TestSessionResult(
            session=session,
            cells=results,
            root=session_root,
            summary_path=summary,
            summary_sha256=summary_sha256,
        )
    except BaseException as error:
        if consumed:
            marker = ledger_root / f"{session}.jsonl"
            first = json.loads(marker.read_text(encoding="utf-8").splitlines()[0])
            write_test_incident(
                authorization,
                session,
                config.outputs.root / "incidents",
                failure_stage="formal_test_session",
                exception_class=type(error).__name__,
                partial_results_viewed=False,
                last_verified_hashes={
                    "attestation": authorization.attestation_sha256,
                    "configuration": authorization.config_sha256,
                },
                test_access_started_at_utc=str(first["test_access_started_at_utc"]),
            )
        raise


def run_test_session(
    config_path: Path,
    session: SessionName,
    authorization: VerifiedTestAuthorization,
) -> TestSessionResult:
    """Consume and execute exactly one authorized formal session."""

    config = load_experiment_config(config_path)
    if not isinstance(config, FrozenTestExperimentConfig):
        raise ValueError("formal Test execution requires the frozen v0.5 configuration")
    return _run_test_session_from_config(
        config_path,
        config,
        session,
        authorization,
        bundle_loader=load_frozen_test_bundle,
        cell_runner=_run_test_cell,
        statistics_writer=_write_session_statistics,
    )


def run_frozen_test_protocol(config_path: Path) -> FrozenTestProtocolResult:
    """Verify authority and automatically consume Run A then Replay B."""

    project_root = find_project_root(config_path)
    if project_root is None:
        raise ValueError("project root not found for the frozen Test protocol")
    authorization = verify_test_authorization(config_path, project_root)
    loaded = load_experiment_config(config_path)
    if not isinstance(loaded, FrozenTestExperimentConfig):
        raise ValueError("formal Test execution requires the frozen v0.5 configuration")
    run_a = run_test_session(config_path, "run-a", authorization)
    run_b = run_test_session(config_path, "run-b", authorization)
    replay = compare_test_replays(
        run_a.root,
        run_b.root,
        run_a.root.parent / "replay_report.json",
    )
    if not replay.release_eligible or replay.capability is None:
        raise ValueError("formal Test replay differs; aggregate and release are blocked")
    aggregate = write_test_aggregates(
        replay.capability,
        loaded.outputs.root / "aggregate-review",
        config_path=config_path,
        attestation_path=authorization.attestation_path,
    )
    return FrozenTestProtocolResult(
        run_a=run_a,
        run_b=run_b,
        replay=replay,
        aggregate=aggregate,
    )


__all__ = [
    "FrozenTestCell",
    "FrozenTestProtocolResult",
    "PreparedTestPredictions",
    "TestCellResult",
    "TestSessionResult",
    "UnlabeledTestPrediction",
    "frozen_test_cells",
    "records_with_train_labels",
    "run_frozen_test_protocol",
    "run_test_session",
    "select_test_matrix_rows",
]
