# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from protein_split_audit.provenance import sha256_file

METHODS = (
    "majority",
    "length_logistic",
    "aac_logistic",
    "kmer3_logistic",
    "nearest_homolog",
    "esm2_35m",
    "esm2_150m",
)
SPLITS = ("random", "cluster70", "cluster50", "cluster30")
LABELS = ("2.7", "3.1", "1.1", "2.1", "4.1")
SUPPORTS = (14, 13, 13, 13, 13)
PAIRS = (
    ("esm2_35m", "aac_logistic"),
    ("esm2_35m", "kmer3_logistic"),
    ("esm2_150m", "aac_logistic"),
    ("esm2_150m", "kmer3_logistic"),
    ("esm2_150m", "esm2_35m"),
)


def _write_json(path: Path, mapping: dict[str, object]) -> None:
    path.write_text(json.dumps(mapping, sort_keys=True) + "\n", encoding="utf-8")


def _interval(metric: str, domain: str) -> dict[str, object]:
    return {
        "metric": metric,
        "point_estimate": 0.5,
        "lower": 0.4,
        "upper": 0.6,
        "requested_iterations": 2000,
        "valid_iterations": 2000,
        "confidence_level": 0.95,
        "group_source": "cluster30_discovery_component",
        "group_count": 20,
        "base_seed": 2026,
        "domain": domain,
        "interval_method": "percentile",
        "quantile_method": "linear",
    }


def enrich_formal_pair(first: Path, second: Path) -> None:
    for root in (first, second):
        for method in METHODS:
            for split in SPLITS:
                cell = root / f"v050-test__{method.replace('_', '-')}__{split}"
                _write_json(
                    cell / "metrics.json",
                    {
                        "accuracy": 0.5,
                        "balanced_accuracy": 0.5,
                        "macro_f1": 0.5,
                        "macro_precision": 0.5,
                        "macro_recall": 0.5,
                        "prediction_coverage": 1.0,
                    },
                )
                (cell / "per_class_metrics.csv").write_text(
                    "label,support,precision,recall,f1\n"
                    + "".join(
                        f"{label},{support},0.5,0.5,0.5\n"
                        for label, support in zip(LABELS, SUPPORTS, strict=True)
                    ),
                    encoding="utf-8",
                )
                (cell / "confusion_matrix.csv").write_text(
                    "true_label,"
                    + ",".join(LABELS)
                    + "\n"
                    + "".join(
                        label
                        + ","
                        + ",".join(
                            str(support if row_index == column_index else 0)
                            for column_index in range(5)
                        )
                        + "\n"
                        for row_index, (label, support) in enumerate(
                            zip(LABELS, SUPPORTS, strict=True)
                        )
                    ),
                    encoding="utf-8",
                )
                _write_json(
                    cell / "confidence_intervals.json",
                    {
                        "intervals": [
                            _interval("macro_f1", f"cell:{split}:macro_f1:{method}"),
                            _interval(
                                "balanced_accuracy",
                                f"cell:{split}:balanced_accuracy:{method}",
                            ),
                        ],
                        "method": method,
                        "split": split,
                    },
                )
                _write_json(
                    cell / "resource_usage.json",
                    {
                        "deterministic_content": False,
                        "peak_rss_bytes": 1024,
                        "prediction_time_seconds": 0.2,
                        "training_time_seconds": 0.3,
                    },
                )
                if method == "nearest_homolog":
                    pq.write_table(
                        pa.table(
                            {
                                "query_accession": pa.array(
                                    [f"P{index:04d}" for index in range(66)], pa.string()
                                ),
                                "nearest_train_accession": pa.array(
                                    [f"T{index:04d}" for index in range(60)] + [None] * 6,
                                    pa.string(),
                                ),
                                "nearest_train_label": pa.array(
                                    ["2.7"] * 60 + [None] * 6, pa.string()
                                ),
                                "predicted_label": pa.array(["2.7"] * 66, pa.string()),
                                "percent_identity": pa.array([0.8] * 60 + [None] * 6, pa.float64()),
                                "query_coverage": pa.array([0.9] * 60 + [None] * 6, pa.float64()),
                                "target_coverage": pa.array([0.9] * 60 + [None] * 6, pa.float64()),
                                "bitscore": pa.array([100.0] * 60 + [None] * 6, pa.float64()),
                                "evalue": pa.array([1e-10] * 60 + [None] * 6, pa.float64()),
                                "no_hit": pa.array([False] * 60 + [True] * 6, pa.bool_()),
                            }
                        ),
                        cell / "nearest_homolog.parquet",
                        compression="zstd",
                        use_dictionary=False,
                    )
                complete_path = cell / "COMPLETE.json"
                complete = json.loads(complete_path.read_bytes())
                complete["artifact_sha256"] = {
                    path.relative_to(cell).as_posix(): sha256_file(path)
                    for path in sorted(cell.rglob("*"))
                    if path.is_file() and path != complete_path
                }
                _write_json(complete_path, complete)

        comparisons = [
            {
                "split_name": split,
                "method_a": method_a,
                "method_b": method_b,
                "metric": metric,
                "comparison_type": "absolute_metric_difference",
                "resampling": "paired",
                "point_a": 0.6,
                "point_b": 0.5,
                "point_difference": 0.1,
                "lower": 0.0,
                "upper": 0.2,
                "requested_iterations": 2000,
                "valid_iterations": 2000,
                "group_count": 20,
                "group_source": "cluster30_discovery_component",
                "base_seed": 2026,
                "domain": f"paired:{split}:{metric}:{method_a}:{method_b}",
                "interval_method": "percentile",
            }
            for split in SPLITS
            for method_a, method_b in PAIRS
            for metric in ("macro_f1", "balanced_accuracy")
        ]
        gaps = [
            {
                "method": method,
                "reference_split": "random",
                "comparison_split": split,
                "metric": "macro_f1",
                "resampling": "independent",
                "random_point": 0.6,
                "cluster_point": 0.5,
                "point_difference": 0.1,
                "lower": 0.0,
                "upper": 0.2,
                "requested_iterations": 2000,
                "valid_iterations": 2000,
                "random_group_count": 20,
                "cluster_group_count": 18,
                "group_source": "cluster30_discovery_component",
                "base_seed": 2026,
                "domain": f"generalization:{method}:random:{split}:macro_f1",
                "interval_method": "percentile",
            }
            for method in METHODS
            for split in ("cluster70", "cluster50", "cluster30")
        ]
        _write_json(
            root / "statistics.json",
            {
                "generalization_gaps": gaps,
                "method_comparisons": comparisons,
                "statistics_identity": {"bootstrap_iterations": 2000},
            },
        )
