# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from protein_split_audit.analysis.aggregate import csv_bytes
from protein_split_audit.analysis.inputs import (
    AnalysisRow,
    PredictionRecord,
    align_prediction_inventories,
    parse_prediction_artifact,
    verify_v050_aggregate_regression,
)
from protein_split_audit.analysis.schemas import METHODS, SPLITS
from protein_split_audit.analysis.stratified_metrics import metric_value
from tests.v060_analysis_helpers import synthetic_rows

LABELS = ("2.7", "3.1", "1.1", "2.1", "4.1")


def _write_predictions(
    path: Path,
    *,
    accessions: tuple[str, ...] = ("SYN0001", "SYN0002", "SYN0003"),
    identities: tuple[float | None, ...] = (0.19, 0.7, None),
    no_hits: tuple[bool, ...] = (False, False, True),
    correct: tuple[bool, ...] = (True, False, True),
) -> None:
    true = ("2.7", "3.1", "1.1")
    predicted = tuple(
        label if is_correct else "2.7" for label, is_correct in zip(true, correct, strict=True)
    )
    table = pa.table(
        {
            "accession": pa.array(accessions, pa.string()),
            "sequence_sha256": pa.array(
                [bytes([index + 1]) * 32 for index in range(len(accessions))],
                pa.binary(32),
            ),
            "split_name": pa.array(["random"] * len(accessions), pa.string()),
            "evaluation_split": pa.array(["test"] * len(accessions), pa.string()),
            "true_label": pa.array(true, pa.string()),
            "predicted_label": pa.array(predicted, pa.string()),
            "correct": pa.array(correct, pa.bool_()),
            **{
                f"score_{label.replace('.', '_')}": pa.array([0.2] * len(accessions), pa.float64())
                for label in LABELS
            },
            "nearest_train_identity": pa.array(identities, pa.float64()),
            "no_hit": pa.array(no_hits, pa.bool_()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def test_prediction_parser_accepts_the_exact_frozen_schema(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path)

    rows = parse_prediction_artifact(path, "majority", "random", expected_count=3)

    assert rows == (
        PredictionRecord(
            "SYN0001", bytes([1]) * 32, "random", "majority", "2.7", "2.7", True, 0.19, False
        ),
        PredictionRecord(
            "SYN0002", bytes([2]) * 32, "random", "majority", "3.1", "2.7", False, 0.7, False
        ),
        PredictionRecord(
            "SYN0003", bytes([3]) * 32, "random", "majority", "1.1", "1.1", True, None, True
        ),
    )


def test_prediction_parser_rejects_duplicate_private_identity(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path, accessions=("SYN0001", "SYN0001", "SYN0003"))

    with pytest.raises(ValueError, match="duplicate private row identity"):
        parse_prediction_artifact(path, "majority", "random", expected_count=3)


@pytest.mark.parametrize(
    "identities,no_hits,message",
    (
        ((None, 0.7, None), (False, False, True), "hit identity must be finite"),
        ((0.19, 1.01, None), (False, False, True), "between zero and one"),
        ((0.19, 0.7, 0.0), (False, False, True), "no-hit identity must be null"),
    ),
)
def test_prediction_parser_rejects_invalid_identity_state(
    tmp_path: Path,
    identities: tuple[float | None, ...],
    no_hits: tuple[bool, ...],
    message: str,
) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path, identities=identities, no_hits=no_hits)

    with pytest.raises(ValueError, match=message):
        parse_prediction_artifact(path, "majority", "random", expected_count=3)


def test_prediction_parser_rejects_changed_column_order(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path)
    table = pq.read_table(path)
    pq.write_table(table.select(list(reversed(table.column_names))), path)

    with pytest.raises(ValueError, match="schema"):
        parse_prediction_artifact(path, "majority", "random", expected_count=3)


def test_prediction_parser_rejects_inconsistent_correct_flag(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path, correct=(False, False, True))

    with pytest.raises(ValueError, match="correct flag"):
        parse_prediction_artifact(path, "majority", "random", expected_count=3)


def test_method_alignment_requires_identical_private_inventory(tmp_path: Path) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    _write_predictions(first)
    _write_predictions(second, accessions=("SYN0001", "SYN0002", "OTHER"))
    rows_a = parse_prediction_artifact(first, "majority", "random", expected_count=3)
    rows_b = parse_prediction_artifact(second, "esm2-150m", "random", expected_count=3)

    with pytest.raises(ValueError, match="identical private row inventory"):
        align_prediction_inventories({"majority": rows_a, "esm2-150m": rows_b})


def test_v050_aggregate_regression_recomputes_every_cell(tmp_path: Path) -> None:
    rows: list[AnalysisRow] = []
    published: list[tuple[object, ...]] = []
    for method in METHODS:
        for split in SPLITS:
            members = synthetic_rows(66, method=method, split=split, component_count=20)
            rows.extend(members)
            published.append(
                (
                    split,
                    method.replace("-", "_"),
                    66,
                    metric_value(members, "accuracy"),
                    metric_value(members, "balanced_accuracy"),
                    metric_value(members, "macro_f1"),
                    0.0,
                    0.0,
                    1.0,
                )
            )
    columns = (
        "split",
        "method",
        "support",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "macro_precision",
        "macro_recall",
        "prediction_coverage",
    )
    path = tmp_path / "test_summary.csv"
    path.write_bytes(csv_bytes(columns, published))

    verify_v050_aggregate_regression(tuple(rows), tmp_path)

    content = path.read_text(encoding="utf-8").replace("0.5,0.5", "0.51,0.5", 1)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        verify_v050_aggregate_regression(tuple(rows), tmp_path)
