# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from protein_split_audit.analysis.schemas import PostTestAnalysisConfig
from protein_split_audit.config import load_analysis_config

PROJECT_ROOT = Path(__file__).parents[1]
CONFIG = PROJECT_ROOT / "configs/analysis/v060-post-test-analysis.yaml"

METHODS = (
    "majority",
    "length-logistic",
    "aac-logistic",
    "kmer3-logistic",
    "nearest-homolog",
    "esm2-35m",
    "esm2-150m",
)
SPLITS = ("random", "cluster70", "cluster50", "cluster30")
IDENTITY_BINS = (
    "identity_00_20",
    "identity_20_30",
    "identity_30_40",
    "identity_40_50",
    "identity_50_70",
    "identity_70_100",
    "no_hit",
)
LENGTH_BINS = (
    "length_050_199",
    "length_200_399",
    "length_400_599",
    "length_600_799",
    "length_800_1000",
)
COMPONENT_SIZE_BINS = (
    "component_singleton",
    "component_02_04",
    "component_05_09",
    "component_10_19",
    "component_20_plus",
)
COMPARISONS = (
    ("esm2-35m", "aac-logistic"),
    ("esm2-35m", "kmer3-logistic"),
    ("esm2-150m", "aac-logistic"),
    ("esm2-150m", "kmer3-logistic"),
    ("esm2-150m", "esm2-35m"),
)


def _mapping() -> dict[str, object]:
    loaded = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _load_mutation(tmp_path: Path, mutation: object) -> PostTestAnalysisConfig:
    root = tmp_path / "project"
    config_dir = root / "configs/analysis"
    config_dir.mkdir(parents=True)
    mapping = deepcopy(_mapping())
    assert callable(mutation)
    mutation(mapping)
    path = config_dir / "v060-post-test-analysis.yaml"
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    return load_analysis_config(path)


def test_v060_config_freezes_the_complete_analysis_contract() -> None:
    config = load_analysis_config(CONFIG)

    assert config.analysis_type == "frozen_test_output_analysis"
    assert config.name == "v060-post-test-analysis"
    assert config.release_target == "v0.6.0"
    assert config.methods == METHODS
    assert config.splits == SPLITS
    assert config.label_order == ("2.7", "3.1", "1.1", "2.1", "4.1")
    assert tuple(item.id for item in config.strata.identity_bins) == IDENTITY_BINS
    assert tuple(item.id for item in config.strata.length_bins) == LENGTH_BINS
    assert tuple(item.id for item in config.strata.component_size_bins) == COMPONENT_SIZE_BINS
    assert tuple((item.method_a, item.method_b) for item in config.comparisons.rq5) == COMPARISONS
    assert (
        config.comparisons.rq6.method_a,
        config.comparisons.rq6.method_b,
    ) == ("esm2-150m", "nearest-homolog")
    assert config.statistics.bootstrap.iterations == 2000
    assert config.statistics.bootstrap.seed == 2026
    assert config.statistics.diagnostic_seeds == (2026, 3407, 42)
    assert config.reporting.minimum_sequences_for_metric == 20
    assert config.reporting.minimum_components_for_ci == 10
    assert config.privacy.suppress_groups_below_sequences == 5
    assert config.privacy.suppress_groups_below_components == 3
    assert config.permissions.new_test_inference_authorized is False
    assert config.permissions.frozen_test_output_analysis_authorized is False
    assert config.inputs.canonical_prediction_session == "run-a"
    assert config.inputs.replay_evidence_session == "run-b"
    assert len(config.inputs.predictions.artifacts) == 28
    assert len(config.inputs.nearest_homolog.artifacts) == 4
    assert config.outputs.formal_sessions == ("analysis-a", "analysis-b")
    assert len(config.outputs.public_artifacts) == 19
    assert config.outputs.refuse_overwrite is True


@pytest.mark.parametrize(
    "mutation, message",
    (
        (lambda value: value["methods"].reverse(), "seven frozen methods"),
        (lambda value: value["splits"].pop(), "four frozen splits"),
        (
            lambda value: value["permissions"].__setitem__("new_test_inference_authorized", True),
            "Input should be False",
        ),
        (
            lambda value: value["permissions"].__setitem__(
                "frozen_test_output_analysis_authorized", True
            ),
            "config cannot authorize",
        ),
        (
            lambda value: value["statistics"]["bootstrap"].__setitem__("iterations", 1000),
            "Input should be 2000",
        ),
        (
            lambda value: value["statistics"].__setitem__("diagnostic_seeds", [2026, 7]),
            "diagnostic seeds",
        ),
        (
            lambda value: value["reporting"].__setitem__("minimum_sequences_for_metric", 5),
            "Input should be 20",
        ),
        (
            lambda value: value["inputs"].__setitem__("canonical_prediction_session", "run-b"),
            "Input should be 'run-a'",
        ),
        (
            lambda value: value["outputs"].__setitem__(
                "formal_sessions", ["analysis-a", "analysis-c"]
            ),
            "formal sessions",
        ),
        (lambda value: value.__setitem__("unexpected", True), "Extra inputs"),
    ),
)
def test_v060_config_rejects_protocol_changes(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _load_mutation(tmp_path, mutation)


@pytest.mark.parametrize("path_value", ("../../../outside", "/tmp/private"))
def test_v060_config_rejects_escaping_or_absolute_paths(
    tmp_path: Path,
    path_value: str,
) -> None:
    def mutate(mapping: dict[str, object]) -> None:
        inputs = mapping["inputs"]
        assert isinstance(inputs, dict)
        run_a = inputs["run_a"]
        assert isinstance(run_a, dict)
        run_a["root"] = path_value

    with pytest.raises(ValueError, match=r"project-relative|inside the project root"):
        _load_mutation(tmp_path, mutate)


def test_v060_config_paths_resolve_from_the_config_location() -> None:
    config = load_analysis_config(CONFIG)

    assert config.inputs.run_a.root == PROJECT_ROOT / "results/runs/v0.5.0-test-r1/run-a"
    assert config.inputs.cohort.manifest == PROJECT_ROOT / "data/manifests/cohorts/pilot-v1.parquet"
    assert config.outputs.release_root == PROJECT_ROOT / "results/released/v0.6.0"
    assert config.attestation == PROJECT_ROOT / "docs/attestations/v0.6.0-analysis-freeze.yaml"
