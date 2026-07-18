# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from protein_split_audit.config import load_experiment_config, load_model_config
from protein_split_audit.evaluation.test_matrix import (
    _write_embedding_artifacts,
    _write_feature_artifacts,
    records_with_train_labels,
)
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.features.length import extract_length
from protein_split_audit.models.esm_linear_probe import (
    save_esm_linear_probe,
    train_esm_linear_probe,
)
from protein_split_audit.models.schemas import EsmLinearProbeConfig
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes, sha256_file
from tests.test_test_partition_isolation import _authorization
from tests.test_v050_train_only_fit import _bundle

PROJECT_ROOT = Path(__file__).parents[1]
CONFIG = PROJECT_ROOT / "configs/experiment/v050-test.yaml"


def _frozen_config() -> FrozenTestExperimentConfig:
    config = load_experiment_config(CONFIG)
    assert isinstance(config, FrozenTestExperimentConfig)
    return config


def _manifest(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_bytes())
    assert isinstance(loaded, dict)
    return loaded


def _without_session(identity: object) -> dict[str, object]:
    assert isinstance(identity, dict)
    return {str(key): value for key, value in identity.items() if str(key) != "session"}


def test_formal_feature_cache_key_excludes_only_the_session_namespace(tmp_path: Path) -> None:
    config = _frozen_config()
    method = next(item for item in config.methods if item.name == "length_logistic")
    bundle = _bundle()
    records = records_with_train_labels(bundle)
    matrix = extract_length(records)
    stages = {session: tmp_path / session for session in ("run-a", "run-b")}

    for session, stage in stages.items():
        stage.mkdir()
        _write_feature_artifacts(
            stage,
            matrix,
            records,
            method=method,
            bundle=bundle,
            authorization=_authorization(),
            session=session,  # type: ignore[arg-type]
        )

    first = _manifest(stages["run-a"] / "feature_cache/manifest.json")
    second = _manifest(stages["run-b"] / "feature_cache/manifest.json")

    assert first["identity"] != second["identity"]
    assert _without_session(first["identity"]) == _without_session(second["identity"])
    assert first["cache_key"] == second["cache_key"]
    assert first["matrix_semantic_sha256"] == second["matrix_semantic_sha256"]


def test_formal_embedding_identity_and_probe_bytes_exclude_session_namespace(
    tmp_path: Path,
) -> None:
    config = _frozen_config()
    method = next(item for item in config.methods if item.name == "esm2_35m")
    bundle = _bundle()
    records = records_with_train_labels(bundle)
    matrix = np.arange(len(records) * 8, dtype=np.float32).reshape(len(records), 8)
    stages = {session: tmp_path / session for session in ("run-a", "run-b")}
    manifest_identities: dict[str, str] = {}

    for session, stage in stages.items():
        stage.mkdir()
        manifest_identities[session] = _write_embedding_artifacts(
            stage,
            matrix,
            records,
            method=method,
            bundle=bundle,
            authorization=_authorization(),
            session=session,  # type: ignore[arg-type]
            batching={"batch_count": 1},
            loading_info={},
        )

    first = _manifest(stages["run-a"] / "embedding_cache/manifest.json")
    second = _manifest(stages["run-b"] / "embedding_cache/manifest.json")

    assert first["identity"] != second["identity"]
    assert _without_session(first["identity"]) == _without_session(second["identity"])
    assert first["cache_key"] == second["cache_key"]
    assert first["deterministic_manifest_sha256"] == manifest_identities["run-a"]
    assert second["deterministic_manifest_sha256"] == manifest_identities["run-b"]
    assert manifest_identities["run-a"] == manifest_identities["run-b"]
    for manifest in (first, second):
        deterministic = dict(manifest)
        observed = deterministic.pop("deterministic_manifest_sha256")
        deterministic["identity"] = _without_session(deterministic["identity"])
        assert observed == sha256_bytes(serialize_canonical_json(deterministic))

    model_config = load_model_config(PROJECT_ROOT / "configs/model/esm_linear_probe.yaml")
    assert isinstance(model_config, EsmLinearProbeConfig)
    model_paths: dict[str, Path] = {}
    for session in ("run-a", "run-b"):
        trained = train_esm_linear_probe(
            matrix,
            records,
            bundle.label_order,
            model_config,
            embedding_manifest_sha256=manifest_identities[session],
        )
        model_paths[session] = save_esm_linear_probe(
            tmp_path / f"{session}.joblib",
            trained,
        )

    assert sha256_file(model_paths["run-a"]) == sha256_file(model_paths["run-b"])
