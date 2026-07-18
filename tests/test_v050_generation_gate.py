# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from protein_split_audit.attestations.test_access import (
    TestFreezeAttestation as FrozenAccessAttestation,
)
from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
HISTORICAL_ATTESTATION = PROJECT_ROOT / "docs/attestations/v0.5.0-test-freeze.yaml"
REVISION_ATTESTATION = PROJECT_ROOT / "docs/attestations/v0.5.0-test-freeze-r1.yaml"
RELEASE_ROOT = PROJECT_ROOT / "results/released/v0.5.0"
RELEASE_NOTES = PROJECT_ROOT / "docs/releases/v0.5.0.md"
HISTORICAL_ATTESTATION_SHA256 = "f419d0ffc3f6985f1dc637a3cb24b5e63b3fc88d0780d63b440f1eec2d43a122"
REVISION_ATTESTATION_SHA256 = "28d03809b662b9ffd9b3d7e69830b203e1a9390887470dc114c38ef16e0e89c9"


def test_v050_version_and_release_state_are_consistent() -> None:
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    config = load_experiment_config(PROJECT_ROOT / "configs/experiment/v050-test.yaml")
    assert isinstance(config, FrozenTestExperimentConfig)

    assert config.evaluation.real_test_access_authorized is False
    if HISTORICAL_ATTESTATION.exists():
        assert sha256_file(HISTORICAL_ATTESTATION) == HISTORICAL_ATTESTATION_SHA256
        loaded = yaml.safe_load(HISTORICAL_ATTESTATION.read_text(encoding="utf-8"))
        FrozenAccessAttestation.model_validate(loaded)
    if REVISION_ATTESTATION.exists():
        assert sha256_file(REVISION_ATTESTATION) == REVISION_ATTESTATION_SHA256
        loaded = yaml.safe_load(REVISION_ATTESTATION.read_text(encoding="utf-8"))
        FrozenAccessAttestation.model_validate(loaded)

    if RELEASE_ROOT.exists():
        assert REVISION_ATTESTATION.exists()
        assert RELEASE_NOTES.is_file()
        assert "version: 0.5.0" in citation
        assert "date-released: 2026-07-18" in citation
    else:
        assert not RELEASE_NOTES.exists()
        assert "version: 0.4.0" in citation
        assert "date-released: 2026-07-16" in citation
    assert not (PROJECT_ROOT / "results/runs/v0.5.0-test-r1").exists()


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
