# SPDX-License-Identifier: Apache-2.0

"""Deterministic, sequence-free aggregate review bundle for frozen Test results."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import shutil
import statistics
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.replay import (
    VerifiedReplayCapability,
    verify_replay_capability_files,
)
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.provenance import sha256_file
from protein_split_audit.publication import validate_sanitized_test_bundle

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
_LABEL_ORDER = ("2.7", "3.1", "1.1", "2.1", "4.1")
_SLUG_TO_METHOD = {method.replace("_", "-"): method for method in _METHOD_ORDER}


@dataclass(frozen=True, slots=True)
class TestAggregateResult:
    """One local-only sanitized aggregate review directory."""

    output_dir: Path
    files: tuple[Path, ...]


def _csv_bytes(header: tuple[str, ...], rows: Sequence[tuple[object, ...]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(
            [format(value, ".17g") if isinstance(value, float) else value for value in row]
        )
    return stream.getvalue().encode("utf-8")


def _json_bytes(mapping: dict[str, object]) -> bytes:
    return (json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _cell_id(method: str, split: str) -> str:
    return f"v050-test__{method.replace('_', '-')}__{split}"


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid aggregate source JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"aggregate source JSON must be a mapping: {path.name}")
    return value


def _finite_metric(mapping: dict[str, object], name: str) -> float:
    value = mapping.get(name)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"invalid Test metric: {name}")
    return float(value)


def _metric_tables(
    root: Path,
) -> tuple[bytes, bytes, bytes, dict[tuple[str, str], dict[str, object]]]:
    summary_rows: list[tuple[object, ...]] = []
    class_rows: list[tuple[object, ...]] = []
    confusion_rows: list[tuple[object, ...]] = []
    metrics_by_cell: dict[tuple[str, str], dict[str, object]] = {}
    for method in _METHOD_ORDER:
        for split in _SPLIT_ORDER:
            cell = root / _cell_id(method, split)
            metrics = _read_json(cell / "metrics.json")
            with (cell / "per_class_metrics.csv").open(encoding="utf-8", newline="") as stream:
                per_class = list(csv.DictReader(stream))
            if tuple(row.get("label") for row in per_class) != _LABEL_ORDER:
                raise ValueError("Test per-class rows differ from the frozen label order")
            supports = [int(row["support"]) for row in per_class]
            if sum(supports) != 66:
                raise ValueError("each Test cell must have support 66")
            summary_rows.append(
                (
                    split,
                    method,
                    66,
                    _finite_metric(metrics, "accuracy"),
                    _finite_metric(metrics, "balanced_accuracy"),
                    _finite_metric(metrics, "macro_f1"),
                    _finite_metric(metrics, "macro_precision"),
                    _finite_metric(metrics, "macro_recall"),
                    _finite_metric(metrics, "prediction_coverage"),
                )
            )
            for row in per_class:
                class_rows.append(
                    (
                        split,
                        method,
                        row["label"],
                        int(row["support"]),
                        float(row["precision"]),
                        float(row["recall"]),
                        float(row["f1"]),
                    )
                )
            with (cell / "confusion_matrix.csv").open(encoding="utf-8", newline="") as stream:
                confusion = list(csv.reader(stream))
            if not confusion or tuple(confusion[0]) != ("true_label", *_LABEL_ORDER):
                raise ValueError("Test confusion matrix header is invalid")
            if tuple(row[0] for row in confusion[1:]) != _LABEL_ORDER:
                raise ValueError("Test confusion matrix rows differ from frozen label order")
            for true_index, true_label in enumerate(_LABEL_ORDER):
                counts = [int(value) for value in confusion[true_index + 1][1:]]
                support = supports[true_index]
                if support <= 0 or sum(counts) != support:
                    raise ValueError("Test confusion counts differ from per-class support")
                fractions = [count / support for count in counts]
                if not math.isclose(sum(fractions), 1.0, rel_tol=0.0, abs_tol=1e-12):
                    raise ValueError("Test confusion row fractions do not sum to one")
                for predicted_label, count, fraction in zip(
                    _LABEL_ORDER, counts, fractions, strict=True
                ):
                    confusion_rows.append(
                        (method, split, true_label, predicted_label, count, fraction)
                    )
            metrics_by_cell[(method, split)] = metrics
    return (
        _csv_bytes(
            (
                "split",
                "method",
                "support",
                "accuracy",
                "balanced_accuracy",
                "macro_f1",
                "macro_precision",
                "macro_recall",
                "prediction_coverage",
            ),
            summary_rows,
        ),
        _csv_bytes(
            ("split", "method", "label", "support", "precision", "recall", "f1"),
            class_rows,
        ),
        _csv_bytes(
            ("method", "split", "true_label", "predicted_label", "count", "row_fraction"),
            confusion_rows,
        ),
        metrics_by_cell,
    )


def _statistics_tables(root: Path) -> tuple[bytes, bytes, bytes]:
    statistics_mapping = _read_json(root / "statistics.json")
    comparisons = statistics_mapping.get("method_comparisons")
    gaps = statistics_mapping.get("generalization_gaps")
    if not isinstance(comparisons, list) or len(comparisons) != 40:
        raise ValueError("formal Test statistics must contain 40 method comparisons")
    if not isinstance(gaps, list) or len(gaps) != 21:
        raise ValueError("formal Test statistics must contain 21 generalization gaps")
    comparison_rows = [
        (
            item["split_name"],
            item["method_a"],
            item["method_b"],
            item["metric"],
            float(item["point_a"]),
            float(item["point_b"]),
            float(item["point_difference"]),
            float(item["lower"]),
            float(item["upper"]),
            item["resampling"],
        )
        for item in comparisons
        if isinstance(item, dict)
    ]
    gap_rows = [
        (
            item["method"],
            str(item["comparison_split"]).replace("cluster", ""),
            item["metric"],
            float(item["random_point"]),
            float(item["cluster_point"]),
            float(item["point_difference"]),
            float(item["lower"]),
            float(item["upper"]),
            item["resampling"],
        )
        for item in gaps
        if isinstance(item, dict)
    ]
    interval_rows: list[tuple[object, ...]] = []
    for method in _METHOD_ORDER:
        for split in _SPLIT_ORDER:
            mapping = _read_json(root / _cell_id(method, split) / "confidence_intervals.json")
            intervals = mapping.get("intervals")
            if not isinstance(intervals, list) or len(intervals) != 2:
                raise ValueError("each Test cell must contain two primary intervals")
            for item in intervals:
                if not isinstance(item, dict):
                    raise ValueError("cell confidence interval must be a mapping")
                interval_rows.append(
                    (
                        "cell",
                        split,
                        method,
                        "",
                        "",
                        item["metric"],
                        float(item["point_estimate"]),
                        float(item["lower"]),
                        float(item["upper"]),
                        int(item["group_count"]),
                        int(item["base_seed"]),
                        int(item["requested_iterations"]),
                        int(item["valid_iterations"]),
                        float(item["confidence_level"]),
                        item["domain"],
                        item["interval_method"],
                        "component",
                    )
                )
    for item in comparisons:
        if isinstance(item, dict):
            interval_rows.append(
                (
                    "method_comparison",
                    item["split_name"],
                    "",
                    item["method_a"],
                    item["method_b"],
                    item["metric"],
                    float(item["point_difference"]),
                    float(item["lower"]),
                    float(item["upper"]),
                    int(item["group_count"]),
                    int(item["base_seed"]),
                    int(item["requested_iterations"]),
                    int(item["valid_iterations"]),
                    0.95,
                    item["domain"],
                    item["interval_method"],
                    item["resampling"],
                )
            )
    for item in gaps:
        if isinstance(item, dict):
            interval_rows.append(
                (
                    "generalization_gap",
                    item["comparison_split"],
                    item["method"],
                    "",
                    "",
                    item["metric"],
                    float(item["point_difference"]),
                    float(item["lower"]),
                    float(item["upper"]),
                    min(int(item["random_group_count"]), int(item["cluster_group_count"])),
                    int(item["base_seed"]),
                    int(item["requested_iterations"]),
                    int(item["valid_iterations"]),
                    0.95,
                    item["domain"],
                    item["interval_method"],
                    item["resampling"],
                )
            )
    if len(interval_rows) != 117:
        raise ValueError("formal Test aggregate must contain exactly 117 confidence intervals")
    return (
        _csv_bytes(
            (
                "split",
                "method_a",
                "method_b",
                "metric",
                "point_a",
                "point_b",
                "absolute_metric_difference",
                "lower",
                "upper",
                "resampling",
            ),
            comparison_rows,
        ),
        _csv_bytes(
            (
                "method",
                "cluster_threshold",
                "metric",
                "random_point",
                "cluster_point",
                "random_minus_cluster",
                "lower",
                "upper",
                "resampling",
            ),
            gap_rows,
        ),
        _csv_bytes(
            (
                "interval_family",
                "split",
                "method",
                "method_a",
                "method_b",
                "metric",
                "point_estimate",
                "lower",
                "upper",
                "group_count",
                "seed",
                "iterations",
                "valid_iterations",
                "confidence_level",
                "domain",
                "interval_method",
                "resampling",
            ),
            interval_rows,
        ),
    )


def _nearest_summary(root: Path) -> bytes:
    rows: list[tuple[object, ...]] = []
    for split in _SPLIT_ORDER:
        table = pq.read_table(root / _cell_id("nearest_homolog", split) / "nearest_homolog.parquet")
        values = table.to_pylist()
        if len(values) != 66:
            raise ValueError("Nearest Homolog detail must contain 66 local Test rows")
        identities = [
            float(row["percent_identity"]) for row in values if row["percent_identity"] is not None
        ]
        no_hit_count = sum(bool(row["no_hit"]) for row in values)
        hit_count = len(values) - no_hit_count
        if hit_count != len(identities):
            raise ValueError("Nearest Homolog hit identity summary is inconsistent")
        rows.append(
            (
                split,
                66,
                hit_count,
                no_hit_count,
                hit_count / 66,
                no_hit_count / 66,
                no_hit_count,
                statistics.fmean(identities) if identities else "",
                statistics.median(identities) if identities else "",
            )
        )
    return _csv_bytes(
        (
            "split",
            "support",
            "hit_count",
            "no_hit_count",
            "hit_rate",
            "no_hit_rate",
            "fallback_count",
            "mean_nearest_identity",
            "median_nearest_identity",
        ),
        rows,
    )


def _environment_summary(first: Path, second: Path) -> bytes:
    first_environment = _read_json(first / _cell_id("majority", "random") / "environment.json")
    observations: list[dict[str, object]] = []
    for session, root in (("run-a", first), ("run-b", second)):
        for method in _METHOD_ORDER:
            for split in _SPLIT_ORDER:
                resource = _read_json(root / _cell_id(method, split) / "resource_usage.json")
                observations.append(
                    {
                        "method": method,
                        "peak_rss_bytes": resource.get("peak_rss_bytes"),
                        "prediction_time_seconds": resource.get("prediction_time_seconds"),
                        "session": session,
                        "split": split,
                        "training_time_seconds": resource.get("training_time_seconds"),
                    }
                )
    return _json_bytes(
        {
            "deterministic_content": False,
            "resource_observations": observations,
            "stable_environment": first_environment,
        }
    )


def _input_hashes(
    capability: VerifiedReplayCapability,
    config_path: Path,
    config: FrozenTestExperimentConfig,
    attestation_path: Path,
) -> bytes:
    root = config_path.parents[2]

    def logical(path: Path) -> str:
        return path.resolve().relative_to(root.resolve()).as_posix()

    cohort = config.cohort.model_dump(mode="json")
    for key in ("manifest", "content_manifest", "fasta"):
        cohort[key] = logical(getattr(config.cohort, key))
    splits: list[dict[str, object]] = []
    for split in config.splits:
        mapping = split.model_dump(mode="json")
        mapping["manifest"] = logical(split.manifest)
        mapping["content_manifest"] = logical(split.content_manifest)
        splits.append(mapping)
    snapshots: list[dict[str, object]] = []
    for snapshot in config.model_snapshots:
        mapping = snapshot.model_dump(mode="json")
        mapping["manifest"] = logical(snapshot.manifest)
        snapshots.append(mapping)

    methods = {
        method.name: {
            logical(path): sha256_file(path)
            for path in (
                method.feature_config,
                method.model_config_path,
                method.embedding_config,
            )
            if path is not None
        }
        for method in config.methods
    }
    cell_completion_hashes = {
        session: {
            _cell_id(method, split): sha256_file(
                session_root / _cell_id(method, split) / "COMPLETE.json"
            )
            for method in _METHOD_ORDER
            for split in _SPLIT_ORDER
        }
        for session, session_root in (
            ("run_a", capability.first_root),
            ("run_b", capability.second_root),
        )
    }
    protocol_path = root / "docs/protocols/v0.5.0-frozen-test-evaluation.md"
    dependency_diff = root / "docs/audits/v0.5.0-dependency-diff.md"
    lock_path = root / "uv.lock"
    return _json_bytes(
        {
            "attestation_sha256": capability.attestation_sha256,
            "bootstrap_component_column": config.cohort.bootstrap_component_column,
            "cell_completion_sha256": cell_completion_hashes,
            "cohort": cohort,
            "configuration": {"path": logical(config_path), "sha256": sha256_file(config_path)},
            "dependency_diff": {
                "path": logical(dependency_diff),
                "sha256": sha256_file(dependency_diff),
            },
            "execution_commit": capability.execution_commit,
            "formal_roots": {
                "run_a_matrix_summary_sha256": sha256_file(
                    capability.first_root / "matrix_summary.json"
                ),
                "run_a_sha256": capability.first_root_sha256,
                "run_a_statistics_sha256": sha256_file(capability.first_root / "statistics.json"),
                "run_b_matrix_summary_sha256": sha256_file(
                    capability.second_root / "matrix_summary.json"
                ),
                "run_b_sha256": capability.second_root_sha256,
                "run_b_statistics_sha256": sha256_file(capability.second_root / "statistics.json"),
            },
            "label_order": list(config.evaluation.label_order),
            "methods": methods,
            "model_snapshots": snapshots,
            "protocol": {
                "path": logical(protocol_path),
                "sha256": sha256_file(protocol_path),
            },
            "replay_report_sha256": capability.report_sha256,
            "splits": splits,
            "test_attestation": {
                "path": logical(config.attestation),
                "sha256": sha256_file(attestation_path),
            },
            "tracked_evidence": [
                {"path": logical(item.path), "sha256": item.sha256}
                for item in config.tracked_evidence
            ],
            "uv_lock": {"path": logical(lock_path), "sha256": sha256_file(lock_path)},
        }
    )


def _publish_directory(output_dir: Path, outputs: dict[str, bytes]) -> tuple[Path, ...]:
    if output_dir.exists():
        raise FileExistsError(f"Test aggregate review directory already exists: {output_dir.name}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        for name, content in outputs.items():
            (staging / name).write_bytes(content)
        os.rename(staging, output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return tuple(output_dir / name for name in outputs)


def write_test_aggregates(
    capability: VerifiedReplayCapability,
    output_dir: Path,
    *,
    config_path: Path,
    attestation_path: Path,
) -> TestAggregateResult:
    """Create the exact twelve-file local aggregate only after exact A/B replay."""

    verify_replay_capability_files(capability)
    if sha256_file(attestation_path) != capability.attestation_sha256:
        raise ValueError("aggregate attestation differs from the verified replay")
    config = load_experiment_config(config_path)
    if not isinstance(config, FrozenTestExperimentConfig):
        raise ValueError("Test aggregate requires the frozen v0.5 configuration")
    summary, per_class, confusion, _metrics = _metric_tables(capability.first_root)
    comparisons, gaps, intervals = _statistics_tables(capability.first_root)
    outputs = {
        "README.md": (
            b"<!-- SPDX-License-Identifier: CC-BY-4.0 -->\n\n"
            b"# ProteinSplitAudit v0.5.0 Test aggregate review\n\n"
            b"This local review bundle contains class-level Pilot summaries from the frozen "
            b"28-cell Test protocol. It contains no row-level predictions or protein records, "
            b"and it does not establish a final benchmark claim.\n"
        ),
        "test_summary.csv": summary,
        "test_per_class.csv": per_class,
        "confusion_matrices.csv": confusion,
        "generalization_gap.csv": gaps,
        "method_comparisons.csv": comparisons,
        "nearest_homolog_summary.csv": _nearest_summary(capability.first_root),
        "confidence_intervals.csv": intervals,
        "environment_summary.json": _environment_summary(
            capability.first_root, capability.second_root
        ),
        "input_hashes.json": _input_hashes(capability, config_path, config, attestation_path),
        "replay_report.json": capability.report_path.read_bytes(),
        "protocol_attestation.yaml": attestation_path.read_bytes(),
    }
    destinations = {output_dir / name: content for name, content in outputs.items()}
    validate_sanitized_test_bundle(destinations)
    files = _publish_directory(output_dir, outputs)
    return TestAggregateResult(output_dir=output_dir, files=files)


__all__ = ["TestAggregateResult", "write_test_aggregates"]
