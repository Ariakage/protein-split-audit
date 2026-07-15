# SPDX-License-Identifier: Apache-2.0

"""Train-only fixed Logistic Regression baseline."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import sparse  # type: ignore[import-untyped]
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from protein_split_audit.features.cache import FeatureMatrix
from protein_split_audit.features.schemas import FeatureConfig
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.schemas import LogisticRegressionModelConfig


class LogisticTrainingError(RuntimeError):
    """Raised when the frozen classifier cannot be fitted safely."""


@dataclass(frozen=True, slots=True)
class TrainedLogistic:
    """One fitted pipeline with a fixed public label order."""

    estimator: Pipeline
    label_order: tuple[str, ...]
    train_accessions: tuple[str, ...]

    def predict(self, matrix: FeatureMatrix) -> tuple[str, ...]:
        """Predict labels without exposing estimator class ordering."""

        return tuple(str(value) for value in self.estimator.predict(matrix))

    def predict_proba(self, matrix: FeatureMatrix) -> npt.NDArray[np.float64]:
        """Return probabilities reordered to the frozen cohort label order."""

        raw = np.asarray(self.estimator.predict_proba(matrix), dtype=np.float64)
        classifier = self.estimator.named_steps["classifier"]
        classes = tuple(str(value) for value in classifier.classes_)
        try:
            columns = [classes.index(label) for label in self.label_order]
        except ValueError as error:
            raise LogisticTrainingError(
                "fitted classes disagree with frozen label order"
            ) from error
        return raw[:, columns]


def _take_rows(matrix: FeatureMatrix, indices: list[int]) -> FeatureMatrix:
    selected = matrix[indices]
    if sparse.issparse(selected):
        return sparse.csr_matrix(selected, dtype=np.float64)
    return np.asarray(selected, dtype=np.float64)


def train_logistic(
    matrix: FeatureMatrix,
    records: Sequence[SequenceRecord],
    label_order: tuple[str, ...],
    feature_config: FeatureConfig,
    model_config: LogisticRegressionModelConfig,
) -> TrainedLogistic:
    """Fit the frozen pipeline using Train rows and labels only."""

    if matrix.shape[0] != len(records):
        raise ValueError("feature row count disagrees with record count")
    train_indices = [index for index, record in enumerate(records) if record.split == "train"]
    if not train_indices:
        raise LogisticTrainingError("Logistic Regression requires Train rows")
    train_matrix = _take_rows(matrix, train_indices)
    train_labels = [records[index].label for index in train_indices]
    if set(train_labels) != set(label_order):
        raise LogisticTrainingError("Train labels disagree with frozen label order")

    classifier = LogisticRegression(
        solver=model_config.solver,
        penalty=model_config.penalty,
        C=model_config.c,
        class_weight=model_config.class_weight,
        max_iter=model_config.max_iter,
        tol=model_config.tol,
        fit_intercept=model_config.fit_intercept,
        random_state=model_config.random_state,
    )
    steps: list[tuple[str, object]] = []
    if feature_config.preprocessing.scaler == "standard_train_only":
        steps.append(("scaler", StandardScaler()))
    steps.append(("classifier", classifier))
    estimator = Pipeline(steps)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(train_matrix, train_labels)
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise LogisticTrainingError("Logistic Regression failed to converge")
    return TrainedLogistic(
        estimator=estimator,
        label_order=label_order,
        train_accessions=tuple(records[index].accession for index in train_indices),
    )


__all__ = ["LogisticTrainingError", "TrainedLogistic", "train_logistic"]
