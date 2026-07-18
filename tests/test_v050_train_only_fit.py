# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import numpy as np

from protein_split_audit.config import load_feature_config, load_model_config
from protein_split_audit.evaluation.test_inputs import (
    FrozenTestBundle,
)
from protein_split_audit.evaluation.test_inputs import (
    TestSequenceRecord as FrozenSequenceRecord,
)
from protein_split_audit.evaluation.test_matrix import (
    records_with_train_labels,
    select_test_matrix_rows,
)
from protein_split_audit.features.length import extract_length
from protein_split_audit.models.logistic_regression import train_logistic
from protein_split_audit.models.majority import fit_majority
from protein_split_audit.models.schemas import LogisticRegressionModelConfig

PROJECT_ROOT = Path(__file__).parents[1]
LABELS = ("2.7", "3.1", "1.1", "2.1", "4.1")


def _bundle() -> FrozenTestBundle:
    records: list[FrozenSequenceRecord] = []
    train_labels: dict[str, str] = {}
    for index in range(20):
        accession = f"TR{index:03d}"
        label = LABELS[index % len(LABELS)]
        records.append(
            FrozenSequenceRecord(accession, bytes([index]) * 32, "train", "A" * 50, f"c{index}")
        )
        train_labels[accession] = label
    for index in range(5):
        records.append(
            FrozenSequenceRecord(
                f"TE{index:03d}", bytes([index + 20]) * 32, "test", "C" * 1000, f"t{index}"
            )
        )
    return FrozenTestBundle(
        records=tuple(sorted(records, key=lambda row: row.accession)),
        train_labels=train_labels,
        label_order=LABELS,
        input_hashes={"test_component_inventory_sha256": "a" * 64},
        split_name="random",
        _cohort_manifest=Path("cohort.parquet"),
    )


def test_classical_training_adapter_contains_train_labels_only() -> None:
    bundle = _bundle()

    records = records_with_train_labels(bundle)

    assert all(record.label in LABELS for record in records if record.split == "train")
    assert all(record.label == "" for record in records if record.split == "test")
    assert not any(record.split == "validation" for record in records)
    majority = fit_majority([record.label for record in records if record.split == "train"])
    assert majority.counts == tuple((label, 4) for label in sorted(LABELS))


def test_length_scaler_and_classifier_fit_train_rows_only() -> None:
    bundle = _bundle()
    records = records_with_train_labels(bundle)
    matrix = extract_length(records)
    feature = load_feature_config(PROJECT_ROOT / "configs/feature/length.yaml")
    model = load_model_config(PROJECT_ROOT / "configs/model/logistic_regression.yaml")
    assert isinstance(model, LogisticRegressionModelConfig)

    trained = train_logistic(matrix, records, bundle.label_order, feature, model)
    scaler = trained.estimator.named_steps["scaler"]

    assert np.asarray(scaler.mean_).tolist() == [50.0]
    assert trained.train_accessions == tuple(
        record.accession for record in records if record.split == "train"
    )
    evaluation = select_test_matrix_rows(matrix, records)
    assert evaluation.shape == (5, 1)
    assert np.asarray(evaluation).ravel().tolist() == [1000.0] * 5
