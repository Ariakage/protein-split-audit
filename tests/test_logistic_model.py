# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest
from sklearn.exceptions import ConvergenceWarning
from sklearn.pipeline import Pipeline

from protein_split_audit.config import load_feature_config, load_model_config
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.schemas import LogisticRegressionModelConfig

PROJECT_ROOT = Path(__file__).parents[1]


def _records() -> tuple[SequenceRecord, ...]:
    rows = (
        ("A0", "1.1", "train"),
        ("A1", "1.1", "train"),
        ("A2", "2.7", "train"),
        ("A3", "2.7", "train"),
        ("A4", "1.1", "validation"),
        ("A5", "2.7", "validation"),
    )
    return tuple(
        SequenceRecord(accession, b"0" * 32, label, split, "ACDE")
        for accession, label, split in rows
    )


@pytest.mark.filterwarnings(
    "ignore:Setting the shape on a NumPy array has been deprecated in NumPy 2.5.*:"
    "DeprecationWarning:joblib.numpy_pickle"
)
def test_length_scaler_fits_train_only_and_reload_is_identical(tmp_path: Path) -> None:
    from protein_split_audit.models.logistic_regression import train_logistic
    from protein_split_audit.models.serialization import load_model, save_model

    matrix = np.array([[1.0], [3.0], [7.0], [9.0], [1000.0], [2000.0]], dtype=np.float64)
    feature = load_feature_config(PROJECT_ROOT / "configs/feature/length.yaml")
    model = load_model_config(PROJECT_ROOT / "configs/model/logistic_regression.yaml")
    assert isinstance(model, LogisticRegressionModelConfig)

    trained = train_logistic(matrix, _records(), ("1.1", "2.7"), feature, model)
    scaler = trained.estimator.named_steps["scaler"]
    assert scaler.mean_.tolist() == [5.0]
    before = trained.predict_proba(matrix[[4, 5]])
    path = save_model(tmp_path / "model.joblib", trained)
    reloaded = load_model(path)
    np.testing.assert_array_equal(reloaded.predict_proba(matrix[[4, 5]]), before)


def test_convergence_warning_fails_training(monkeypatch: pytest.MonkeyPatch) -> None:
    from protein_split_audit.models.logistic_regression import LogisticTrainingError, train_logistic

    def warn_fit(self: Pipeline, x: object, y: object, **kwargs: object) -> Pipeline:
        warnings.warn("did not converge", ConvergenceWarning, stacklevel=2)
        return self

    monkeypatch.setattr(Pipeline, "fit", warn_fit)
    matrix = np.array([[1.0], [3.0], [7.0], [9.0], [1000.0], [2000.0]], dtype=np.float64)
    feature = load_feature_config(PROJECT_ROOT / "configs/feature/length.yaml")
    model = load_model_config(PROJECT_ROOT / "configs/model/logistic_regression.yaml")
    assert isinstance(model, LogisticRegressionModelConfig)

    with pytest.raises(LogisticTrainingError, match="converge"):
        train_logistic(matrix, _records(), ("1.1", "2.7"), feature, model)
