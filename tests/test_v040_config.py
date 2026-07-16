# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.schemas import EsmExperimentConfig, ExperimentConfig

PROJECT_ROOT = Path(__file__).parents[1]


def test_v040_validation_config_is_exact_and_v030_still_loads() -> None:
    v040 = load_experiment_config(PROJECT_ROOT / "configs/experiment/v040-validation.yaml")
    v030 = load_experiment_config(PROJECT_ROOT / "configs/experiment/v030-validation.yaml")

    assert isinstance(v040, EsmExperimentConfig)
    assert isinstance(v030, ExperimentConfig)
    assert tuple(model.name for model in v040.models) == ("esm2_35m", "esm2_150m")
    assert tuple(split.name for split in v040.splits) == (
        "random",
        "cluster70",
        "cluster50",
        "cluster30",
    )
    assert v040.cell_count == 8
    assert v040.evaluation.real_test_access_authorized is False
    assert v040.runtime.device == "cpu"
    assert v040.runtime.dtype == "float32"


def test_v040_config_rejects_changed_model_order(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "configs/experiment/v040-validation.yaml"
    mapping = yaml.safe_load(source.read_text(encoding="utf-8"))
    mapping["models"].reverse()
    path = tmp_path / "v040.yaml"
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValidationError, match="two frozen ESM models in order"):
        load_experiment_config(path)


def test_v040_test_config_remains_denied() -> None:
    config = load_experiment_config(PROJECT_ROOT / "configs/experiment/v040-test-gated.yaml")

    assert isinstance(config, EsmExperimentConfig)
    assert config.evaluation.split == "test"
    assert config.evaluation.real_test_access_authorized is False
    assert config.attestation is not None
