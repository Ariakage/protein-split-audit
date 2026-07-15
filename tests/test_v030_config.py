# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import protein_split_audit.config as config_module

PROJECT_ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path) -> Any:
    loader = getattr(config_module, name, None)
    assert callable(loader), f"{name} must be implemented"
    return loader(path)


def test_frozen_feature_configs_are_explicit() -> None:
    length = _load("load_feature_config", PROJECT_ROOT / "configs/feature/length.yaml")
    aac = _load("load_feature_config", PROJECT_ROOT / "configs/feature/aac.yaml")
    kmer = _load("load_feature_config", PROJECT_ROOT / "configs/feature/kmer3.yaml")

    assert (length.kind, length.feature_count, length.preprocessing.scaler) == (
        "length",
        1,
        "standard_train_only",
    )
    assert (aac.kind, aac.feature_count, aac.preprocessing.scaler) == (
        "aac",
        20,
        "standard_train_only",
    )
    assert (kmer.kind, kmer.feature_count, kmer.preprocessing.scaler) == (
        "kmer3",
        8000,
        "none",
    )
    assert kmer.k == 3
    assert kmer.sparse_format == "csr"
    assert kmer.dtype == "float64"


def test_frozen_model_configs_are_exact() -> None:
    majority = _load("load_model_config", PROJECT_ROOT / "configs/model/majority.yaml")
    logistic = _load("load_model_config", PROJECT_ROOT / "configs/model/logistic_regression.yaml")
    nearest = _load("load_model_config", PROJECT_ROOT / "configs/model/nearest_homolog.yaml")

    assert majority.type == "majority"
    assert majority.tie_break == "label_lexicographic_ascending"
    assert logistic.type == "logistic_regression"
    assert logistic.solver == "lbfgs"
    assert logistic.penalty == "l2"
    assert logistic.c == 1.0
    assert logistic.class_weight == "balanced"
    assert logistic.max_iter == 5000
    assert logistic.tol == 0.0001
    assert nearest.type == "nearest_homolog"
    assert nearest.runtime.threads == 8
    assert nearest.search.minimum_coverage == 0.80
    assert nearest.search.evalue_threshold == 0.001
    assert nearest.hit_order == (
        "bitscore_desc",
        "evalue_asc",
        "percent_identity_desc",
        "query_coverage_desc",
        "target_coverage_desc",
        "target_accession_asc",
    )


def test_experiment_configs_are_validation_only_and_test_denied() -> None:
    validation = _load(
        "load_experiment_config", PROJECT_ROOT / "configs/experiment/v030-validation.yaml"
    )
    blocked_test = _load(
        "load_experiment_config", PROJECT_ROOT / "configs/experiment/v030-test.yaml"
    )

    assert validation.evaluation.split == "validation"
    assert validation.runtime.seed == 42
    assert validation.runtime.feature_threads == 1
    assert validation.runtime.mmseqs_threads == 8
    assert len(validation.splits) == 4
    assert len(validation.baselines) == 5
    assert blocked_test.evaluation.split == "test"
    assert blocked_test.evaluation.real_test_access_authorized is False
    assert blocked_test.attestation.name == "v0.3.0-protocol-freeze.yaml"


def test_kmer_config_rejects_scaler(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "configs/feature/kmer3.yaml"
    mapping = yaml.safe_load(source.read_text(encoding="utf-8"))
    mapping["preprocessing"]["scaler"] = "standard_train_only"
    path = tmp_path / "kmer3.yaml"
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8", newline="\n")

    with pytest.raises(ValidationError, match="kmer3 requires scaler none"):
        _load("load_feature_config", path)


def test_nearest_config_rejects_non_frozen_threads(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "configs/model/nearest_homolog.yaml"
    mapping = yaml.safe_load(source.read_text(encoding="utf-8"))
    mapping["runtime"]["threads"] = 4
    path = tmp_path / "nearest.yaml"
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8", newline="\n")

    with pytest.raises(ValidationError):
        _load("load_model_config", path)
