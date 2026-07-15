# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import yaml

from protein_split_audit.features.extract import extract_feature_cache
from tests.v030_helpers import write_tiny_experiment

PROJECT_ROOT = Path(__file__).parents[1]


def test_standalone_logistic_training_is_bound_to_feature_and_split(tmp_path: Path) -> None:
    from protein_split_audit.models.standalone import train_cached_model

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    mapping = yaml.safe_load(experiment.config.read_text(encoding="utf-8"))
    split = mapping["splits"][0]
    cohort = mapping["cohort"]
    cache = extract_feature_cache(
        config_path=PROJECT_ROOT / "configs/feature/length.yaml",
        cohort_manifest=Path(cohort["manifest"]),
        cohort_content_manifest=Path(cohort["content_manifest"]),
        cohort_fasta=Path(cohort["fasta"]),
        split_manifest=Path(split["manifest"]),
        split_content_manifest=Path(split["content_manifest"]),
        cache_root=tmp_path / "cache",
    )
    output = tmp_path / "model-run"
    result = train_cached_model(
        feature_manifest=cache.directory / "manifest.json",
        split_manifest=Path(split["manifest"]),
        split_content_manifest=Path(split["content_manifest"]),
        config_path=PROJECT_ROOT / "configs/model/logistic_regression.yaml",
        output_dir=output,
    )

    assert result.model_path == output / "model.joblib"
    assert result.model_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["training_split"] == "train"
    assert manifest["feature_manifest_sha256"]
