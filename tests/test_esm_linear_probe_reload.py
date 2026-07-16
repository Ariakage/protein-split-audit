# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.config import load_model_config
from protein_split_audit.models.esm_linear_probe import (
    load_esm_linear_probe,
    save_esm_linear_probe,
    train_esm_linear_probe,
)
from protein_split_audit.models.schemas import EsmLinearProbeConfig
from tests.test_esm_linear_probe import LABELS, _training_data

PROJECT_ROOT = Path(__file__).parents[1]


def test_esm_linear_probe_reload_preserves_predictions(tmp_path: Path) -> None:
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
    path = save_esm_linear_probe(tmp_path / "model.joblib", trained)

    loaded = load_esm_linear_probe(path)

    assert loaded.predict(matrix) == trained.predict(matrix)
    assert loaded.predict_proba(matrix).tobytes() == trained.predict_proba(matrix).tobytes()
