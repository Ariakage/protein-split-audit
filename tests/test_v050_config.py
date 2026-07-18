# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig

PROJECT_ROOT = Path(__file__).parents[1]
CONFIG = PROJECT_ROOT / "configs/experiment/v050-test.yaml"

METHODS = (
    "majority",
    "length_logistic",
    "aac_logistic",
    "kmer3_logistic",
    "nearest_homolog",
    "esm2_35m",
    "esm2_150m",
)
SPLITS = ("random", "cluster70", "cluster50", "cluster30")


def _mapping() -> dict[str, object]:
    loaded = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _load_mutation(tmp_path: Path, mutation: object) -> FrozenTestExperimentConfig:
    root = tmp_path / "project"
    config_dir = root / "configs/experiment"
    config_dir.mkdir(parents=True)
    mapping = deepcopy(_mapping())
    assert callable(mutation)
    mutation(mapping)
    path = config_dir / "v050-test.yaml"
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    loaded = load_experiment_config(path)
    assert isinstance(loaded, FrozenTestExperimentConfig)
    return loaded


def test_v050_config_freezes_the_exact_matrix_and_statistics() -> None:
    config = load_experiment_config(CONFIG)

    assert isinstance(config, FrozenTestExperimentConfig)
    assert config.experiment_type == "frozen_test"
    assert tuple(method.name for method in config.methods) == METHODS
    assert tuple(split.name for split in config.splits) == SPLITS
    assert config.cell_count == 28
    assert config.evaluation.fit_partition == "train"
    assert config.evaluation.evaluation_partition == "test"
    assert config.evaluation.validation_policy == "excluded"
    assert config.evaluation.real_test_access_authorized is False
    assert config.formal_sessions == ("run-a", "run-b")
    assert config.statistics.bootstrap.iterations == 2000
    assert config.statistics.bootstrap.confidence_level == 0.95
    assert config.statistics.bootstrap.lower_quantile == 0.025
    assert config.statistics.bootstrap.upper_quantile == 0.975
    assert config.statistics.bootstrap.seed == 2026
    assert config.statistics.bootstrap.unit == "cluster30_discovery_component"
    assert config.statistics.bootstrap.interval_method == "percentile"
    assert config.outputs.refuse_overwrite is True
    assert config.outputs.root == PROJECT_ROOT / "results/runs/v0.5.0-test"
    assert config.attestation == PROJECT_ROOT / "docs/attestations/v0.5.0-test-freeze.yaml"


@pytest.mark.parametrize(
    "mutation, message",
    (
        (lambda value: value["methods"].reverse(), "seven frozen methods in order"),
        (lambda value: value["methods"].pop(), "seven frozen methods in order"),
        (lambda value: value["methods"].append(deepcopy(value["methods"][0])), "seven frozen"),
        (lambda value: value["splits"].reverse(), "four frozen splits in order"),
        (lambda value: value["splits"].pop(), "four frozen splits in order"),
        (lambda value: value.__setitem__("formal_sessions", ["run-a"]), "formal sessions"),
        (
            lambda value: value["evaluation"].__setitem__("real_test_access_authorized", True),
            "Input should be False",
        ),
        (
            lambda value: value["evaluation"].__setitem__("fit_partition", "validation"),
            "Input should be 'train'",
        ),
        (
            lambda value: value["outputs"].__setitem__("root", "../../results/runs/other"),
            "fixed v0.5 Test run root",
        ),
        (lambda value: value.__setitem__("hyperparameters", {"C": 10}), "Extra inputs"),
    ),
)
def test_v050_config_rejects_protocol_changes(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _load_mutation(tmp_path, mutation)


def test_v050_config_rejects_paths_outside_the_project(tmp_path: Path) -> None:
    def escape(mapping: dict[str, object]) -> None:
        cohort = mapping["cohort"]
        assert isinstance(cohort, dict)
        cohort["manifest"] = "../../../outside.parquet"

    with pytest.raises(ValueError, match="must remain inside the project root"):
        _load_mutation(tmp_path, escape)


def test_v050_config_keeps_v030_and_v040_loaders_compatible() -> None:
    assert (
        load_experiment_config(PROJECT_ROOT / "configs/experiment/v030-validation.yaml").name
        == "v030-classical-validation"
    )
    assert (
        load_experiment_config(PROJECT_ROOT / "configs/experiment/v040-validation.yaml").name
        == "v040-esm2-validation"
    )
