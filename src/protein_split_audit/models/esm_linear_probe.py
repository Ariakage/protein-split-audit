# SPDX-License-Identifier: Apache-2.0

"""Frozen Train-only Logistic Regression probe over ESM embeddings."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import joblib  # type: ignore[import-untyped]
import numpy as np
import numpy.typing as npt
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.logistic_regression import (
    LogisticTrainingError,
    build_frozen_logistic_classifier,
)
from protein_split_audit.models.scaler import FittedTrainScaler, fit_train_scaler
from protein_split_audit.models.schemas import (
    EsmLinearProbeConfig,
    LogisticRegressionModelConfig,
)


@dataclass(frozen=True, slots=True)
class TrainedEsmLinearProbe:
    """Fitted Train-only scaler/classifier with stable label ordering."""

    scaler: FittedTrainScaler
    classifier: LogisticRegression
    label_order: tuple[str, ...]
    train_accessions: tuple[str, ...]

    def predict(self, matrix: npt.NDArray[np.float32]) -> tuple[str, ...]:
        """Predict labels for aligned embeddings."""

        transformed = self.scaler.transform(matrix)
        return tuple(str(value) for value in self.classifier.predict(transformed))

    def predict_proba(self, matrix: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
        """Return probabilities reordered to the frozen cohort label order."""

        raw = np.asarray(
            self.classifier.predict_proba(self.scaler.transform(matrix)), dtype=np.float64
        )
        classes = tuple(str(value) for value in self.classifier.classes_)
        try:
            columns = [classes.index(label) for label in self.label_order]
        except ValueError as error:
            raise LogisticTrainingError(
                "fitted classes disagree with frozen label order"
            ) from error
        return raw[:, columns]


def _logistic_config(config: EsmLinearProbeConfig) -> LogisticRegressionModelConfig:
    return LogisticRegressionModelConfig.model_validate(
        {
            "schema_version": config.schema_version,
            "type": "logistic_regression",
            "solver": config.solver,
            "penalty": config.penalty,
            "C": config.c,
            "class_weight": config.class_weight,
            "max_iter": config.max_iter,
            "tol": config.tol,
            "fit_intercept": config.fit_intercept,
            "random_state": config.random_state,
        }
    )


def train_esm_linear_probe(
    matrix: npt.NDArray[np.float32],
    records: Sequence[SequenceRecord],
    label_order: tuple[str, ...],
    config: EsmLinearProbeConfig,
    *,
    embedding_manifest_sha256: str,
) -> TrainedEsmLinearProbe:
    """Fit the prespecified classifier using Train labels and embeddings only."""

    scaler = fit_train_scaler(
        matrix,
        records,
        embedding_manifest_sha256=embedding_manifest_sha256,
    )
    train_indices = [index for index, record in enumerate(records) if record.split == "train"]
    train_labels = [records[index].label for index in train_indices]
    if set(train_labels) != set(label_order):
        raise LogisticTrainingError("Train labels disagree with frozen label order")
    classifier = build_frozen_logistic_classifier(_logistic_config(config))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        classifier.fit(scaler.transform(matrix)[train_indices], train_labels)
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise LogisticTrainingError("ESM Linear Probe failed to converge")
    return TrainedEsmLinearProbe(
        scaler=scaler,
        classifier=classifier,
        label_order=label_order,
        train_accessions=tuple(records[index].accession for index in train_indices),
    )


def save_esm_linear_probe(path: Path, model: TrainedEsmLinearProbe) -> Path:
    """Write one local fitted probe without overwrite."""

    if path.exists():
        raise FileExistsError(f"model artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return path


def load_esm_linear_probe(path: Path) -> TrainedEsmLinearProbe:
    """Load and type-check one local fitted ESM probe."""

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Setting the shape on a NumPy array has been deprecated.*",
            category=DeprecationWarning,
            module=r"joblib\.numpy_pickle",
        )
        value = joblib.load(path)
    if not isinstance(value, TrainedEsmLinearProbe):
        raise ValueError("serialized artifact is not a ProteinSplitAudit ESM Linear Probe")
    return value


__all__ = [
    "TrainedEsmLinearProbe",
    "load_esm_linear_probe",
    "save_esm_linear_probe",
    "train_esm_linear_probe",
]
