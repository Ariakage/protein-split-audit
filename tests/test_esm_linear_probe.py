# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np

from protein_split_audit.config import load_model_config
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.esm_linear_probe import train_esm_linear_probe
from protein_split_audit.models.schemas import EsmLinearProbeConfig

PROJECT_ROOT = Path(__file__).parents[1]
LABELS = ("1.1", "2.1", "2.7", "3.1", "4.1")


def _training_data() -> tuple[np.ndarray, tuple[SequenceRecord, ...]]:
    rows: list[np.ndarray] = []
    records: list[SequenceRecord] = []
    for class_index, label in enumerate(LABELS):
        for replicate in range(2):
            vector = np.zeros(5, dtype=np.float32)
            vector[class_index] = 5.0 + replicate
            rows.append(vector)
            records.append(
                SequenceRecord(
                    f"T{class_index}{replicate}",
                    bytes([class_index + 1]) * 32,
                    label,
                    "train",
                    "A" * 50,
                )
            )
        rows.append(np.eye(5, dtype=np.float32)[class_index] * 5.5)
        records.append(
            SequenceRecord(
                f"V{class_index}",
                bytes([class_index + 10]) * 32,
                label,
                "validation",
                "A" * 50,
            )
        )
    return np.stack(rows), tuple(records)


def test_esm_linear_probe_uses_frozen_classifier_and_train_only_rows() -> None:
    config = load_model_config(PROJECT_ROOT / "configs/model/esm_linear_probe.yaml")
    assert isinstance(config, EsmLinearProbeConfig)
    matrix, records = _training_data()

    trained = train_esm_linear_probe(
        matrix,
        records,
        LABELS,
        config,
        embedding_manifest_sha256="2" * 64,
    )

    classifier = trained.classifier
    assert classifier.solver == "lbfgs"
    assert classifier.C == 1.0
    assert classifier.class_weight == "balanced"
    assert classifier.max_iter == 5000
    assert classifier.tol == 0.0001
    assert trained.train_accessions == tuple(
        record.accession for record in records if record.split == "train"
    )
    assert trained.predict(matrix[10:11]) in (("3.1",), ("4.1",), ("2.7",), ("2.1",), ("1.1",))
