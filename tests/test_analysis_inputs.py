# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import protein_split_audit.analysis.authorization as authorization_module
import protein_split_audit.analysis.inputs as inputs_module
from protein_split_audit.analysis.aggregate import csv_bytes
from protein_split_audit.analysis.inputs import (
    AnalysisRow,
    PredictionRecord,
    align_prediction_inventories,
    load_frozen_analysis_rows,
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
    no_hits: tuple[bool | None, ...] = (False, False, True),
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

    rows = parse_prediction_artifact(path, "nearest-homolog", "random", expected_count=3)

    assert rows == (
        PredictionRecord(
            "SYN0001",
            bytes([1]) * 32,
            "random",
            "nearest-homolog",
            "2.7",
            "2.7",
            True,
            0.19,
            False,
        ),
        PredictionRecord(
            "SYN0002",
            bytes([2]) * 32,
            "random",
            "nearest-homolog",
            "3.1",
            "2.7",
            False,
            0.7,
            False,
        ),
        PredictionRecord(
            "SYN0003",
            bytes([3]) * 32,
            "random",
            "nearest-homolog",
            "1.1",
            "1.1",
            True,
            None,
            True,
        ),
    )


def test_prediction_parser_accepts_null_neighbor_metadata_for_non_homolog(
    tmp_path: Path,
) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(
        path,
        identities=(None, None, None),
        no_hits=(None, None, None),
    )

    rows = parse_prediction_artifact(path, "majority", "random", expected_count=3)

    assert all(row.nearest_train_identity is None and row.no_hit is None for row in rows)


def test_prediction_parser_rejects_populated_neighbor_metadata_for_non_homolog(
    tmp_path: Path,
) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path)

    with pytest.raises(ValueError, match="must be null for non-Nearest-Homolog"):
        parse_prediction_artifact(path, "majority", "random", expected_count=3)


def test_prediction_parser_rejects_duplicate_private_identity(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path, accessions=("SYN0001", "SYN0001", "SYN0003"))

    with pytest.raises(ValueError, match="duplicate private row identity"):
        parse_prediction_artifact(path, "nearest-homolog", "random", expected_count=3)


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
    no_hits: tuple[bool | None, ...],
    message: str,
) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path, identities=identities, no_hits=no_hits)

    with pytest.raises(ValueError, match=message):
        parse_prediction_artifact(path, "nearest-homolog", "random", expected_count=3)


def test_prediction_parser_rejects_changed_column_order(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path)
    table = pq.read_table(path)
    pq.write_table(table.select(list(reversed(table.column_names))), path)

    with pytest.raises(ValueError, match="schema"):
        parse_prediction_artifact(path, "nearest-homolog", "random", expected_count=3)


def test_prediction_parser_rejects_inconsistent_correct_flag(tmp_path: Path) -> None:
    path = tmp_path / "predictions.parquet"
    _write_predictions(path, correct=(False, False, True))

    with pytest.raises(ValueError, match="correct flag"):
        parse_prediction_artifact(path, "nearest-homolog", "random", expected_count=3)


def test_method_alignment_requires_identical_private_inventory(tmp_path: Path) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    _write_predictions(first, identities=(None, None, None), no_hits=(None, None, None))
    _write_predictions(
        second,
        accessions=("SYN0001", "SYN0002", "OTHER"),
        identities=(None, None, None),
        no_hits=(None, None, None),
    )
    rows_a = parse_prediction_artifact(first, "majority", "random", expected_count=3)
    rows_b = parse_prediction_artifact(second, "esm2-150m", "random", expected_count=3)

    with pytest.raises(ValueError, match="identical private row inventory"):
        align_prediction_inventories({"majority": rows_a, "esm2-150m": rows_b})


def test_frozen_row_loader_uses_authenticated_nearest_detail_for_every_method(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cohort: dict[tuple[str, bytes], inputs_module._CohortRow] = {}
    test_rows: dict[str, dict[tuple[str, bytes], inputs_module._CohortRow]] = {}
    details: dict[str, inputs_module._NearestDetail] = {}
    for index, split in enumerate(SPLITS):
        accession = f"SYN-{split}"
        digest = bytes([index + 1]) * 32
        member = inputs_module._CohortRow(
            accession=accession,
            sequence_sha256=digest,
            label="2.7",
            length=200,
            component_id=f"component-{split}",
            component_size=1,
        )
        cohort[(accession, digest)] = member
        test_rows[split] = {(accession, digest): member}
        details[split] = inputs_module._NearestDetail(
            query_accession=accession,
            nearest_train_accession=f"TRAIN-{split}",
            nearest_train_label="2.7",
            predicted_label="2.7",
            percent_identity=0.42,
            query_coverage=0.8,
            target_coverage=0.9,
            bitscore=50.0,
            evalue=1e-6,
            no_hit=False,
        )

    prediction_artifacts = tuple(
        SimpleNamespace(method=method, split=split, relative_path=Path(f"{method}-{split}"))
        for method in METHODS
        for split in SPLITS
    )
    nearest_artifacts = tuple(
        SimpleNamespace(split=split, relative_path=Path(f"nearest-{split}")) for split in SPLITS
    )
    config = SimpleNamespace(
        inputs=SimpleNamespace(
            run_a=SimpleNamespace(root=tmp_path),
            predictions=SimpleNamespace(artifacts=prediction_artifacts),
            nearest_homolog=SimpleNamespace(artifacts=nearest_artifacts),
            reviewed_aggregate=SimpleNamespace(root=tmp_path),
        )
    )

    monkeypatch.setattr(
        authorization_module, "require_verified_analysis_authorization", lambda _: None
    )
    monkeypatch.setattr(inputs_module, "_load_cohort", lambda _: cohort)
    monkeypatch.setattr(inputs_module, "_load_split_test_rows", lambda *_: test_rows)
    monkeypatch.setattr(
        inputs_module,
        "parse_nearest_detail",
        lambda _path, split: (details[split],),
    )

    def parse_prediction(
        _path: Path,
        method: str,
        split: str,
        *,
        expected_count: int = 66,
    ) -> tuple[PredictionRecord, ...]:
        assert expected_count == 66
        member = next(iter(test_rows[split].values()))
        detail = details[split]
        is_nearest = method == "nearest-homolog"
        return (
            PredictionRecord(
                accession=member.accession,
                sequence_sha256=member.sequence_sha256,
                split_name=split,
                method=method,
                true_label=member.label,
                predicted_label="2.7",
                correct=True,
                nearest_train_identity=detail.percent_identity if is_nearest else None,
                no_hit=detail.no_hit if is_nearest else None,
            ),
        )

    monkeypatch.setattr(inputs_module, "parse_prediction_artifact", parse_prediction)
    monkeypatch.setattr(inputs_module, "verify_v050_aggregate_regression", lambda *_: None)

    rows = load_frozen_analysis_rows(config, object())

    assert len(rows) == len(METHODS) * len(SPLITS)
    assert all(row.nearest_train_identity == 0.42 and row.no_hit is False for row in rows)


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
