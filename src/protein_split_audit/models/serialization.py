# SPDX-License-Identifier: Apache-2.0

"""Local joblib serialization for classical fitted models."""

from __future__ import annotations

from pathlib import Path

import joblib  # type: ignore[import-untyped]

from protein_split_audit.models.logistic_regression import TrainedLogistic


def save_model(path: Path, model: TrainedLogistic) -> Path:
    """Write one fitted model without replacing an existing artifact."""

    if path.exists():
        raise FileExistsError(f"model artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return path


def load_model(path: Path) -> TrainedLogistic:
    """Load and type-check one local fitted model."""

    value = joblib.load(path)
    if not isinstance(value, TrainedLogistic):
        raise ValueError("serialized artifact is not a ProteinSplitAudit Logistic model")
    return value


__all__ = ["load_model", "save_model"]
