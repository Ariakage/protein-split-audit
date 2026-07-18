# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from protein_split_audit import __version__
from protein_split_audit.attestations.test_access import (
    TestFreezeAttestation as FrozenAccessAttestation,
)
from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig

PROJECT_ROOT = Path(__file__).parents[1]
ATTESTATION = PROJECT_ROOT / "docs/attestations/v0.5.0-test-freeze.yaml"


def test_generation_a_version_and_release_state_are_consistent() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    config = load_experiment_config(PROJECT_ROOT / "configs/experiment/v050-test.yaml")
    assert isinstance(config, FrozenTestExperimentConfig)

    assert __version__ == "0.5.0"
    assert 'version = "0.5.0"' in pyproject
    assert re.search(r'\[\[package\]\]\nname = "protein-split-audit"\nversion = "0\.5\.0"', lock)
    assert config.evaluation.real_test_access_authorized is False
    assert "version: 0.4.0" in citation

    if ATTESTATION.exists():
        loaded = yaml.safe_load(ATTESTATION.read_text(encoding="utf-8"))
        FrozenAccessAttestation.model_validate(loaded)
    else:
        assert not (PROJECT_ROOT / "results/released/v0.5.0").exists()
        assert not (PROJECT_ROOT / "docs/releases/v0.5.0.md").exists()


def test_dependency_diff_allows_only_the_root_version_change() -> None:
    report = (PROJECT_ROOT / "docs/audits/v0.5.0-dependency-diff.md").read_text(encoding="utf-8")

    assert "protein-split-audit` | `0.4.0` | `0.5.0" in report
    assert "175 complete third-party package objects" in report
    assert report.count("dc298e10c999a1bc61dd29b40fde313ee31475440be17c4d2d4d59e95b4229ed") == 2
    assert "No other lockfile change is approved" in report


def test_generation_candidate_contains_no_tracked_private_artifacts() -> None:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    candidates = tuple(line for line in completed.stdout.splitlines() if line)
    forbidden_suffixes = (
        ".ckpt",
        ".fasta",
        ".joblib",
        ".jsonl",
        ".log",
        ".npy",
        ".npz",
        ".parquet",
        ".pth",
        ".pt",
        ".safetensors",
    )
    forbidden_prefixes = (
        "cache/features/",
        "cache/models/",
        "data/interim/",
        "data/processed/",
        "data/raw/",
        "models/",
        "results/runs/",
    )
    violations = [
        path
        for path in candidates
        if path.endswith(forbidden_suffixes) or path.startswith(forbidden_prefixes)
    ]
    assert violations == []
