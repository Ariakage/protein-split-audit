# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from protein_split_audit import __version__
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]


def test_generation_a_version_and_release_boundary() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")

    assert __version__ == "0.6.0"
    assert 'version = "0.6.0"' in pyproject
    assert 'name = "protein-split-audit"\nversion = "0.6.0"' in lock
    assert "version: 0.5.0" in citation
    assert not (PROJECT_ROOT / "docs/attestations/v0.6.0-analysis-freeze.yaml").exists()
    assert not (PROJECT_ROOT / "results/released/v0.6.0").exists()
    assert not (PROJECT_ROOT / "docs/releases/v0.6.0.md").exists()


def test_lock_diff_changes_only_the_root_project_version() -> None:
    historical = subprocess.run(
        ["git", "show", "v0.5.0:uv.lock"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    old = tomllib.loads(historical.decode("utf-8"))
    new = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    old_root = next(item for item in old["package"] if item["name"] == "protein-split-audit")
    new_root = next(item for item in new["package"] if item["name"] == "protein-split-audit")
    assert old_root.pop("version") == "0.5.0"
    assert new_root.pop("version") == "0.6.0"
    assert old == new
    assert sha256_file(PROJECT_ROOT / "uv.lock") == (
        "efe81a00b6c2cbcda06ec89b3720a75ff4cac11e7edfe46d46ba08748a2fd5d3"
    )


def test_dependency_audit_records_the_normalized_identity() -> None:
    report = (PROJECT_ROOT / "docs/audits/v0.6.0-dependency-diff.md").read_text(encoding="utf-8")
    assert "175 complete third-party package objects" in report
    assert "0.5.0` | `0.6.0" in report
    assert report.count("dc298e10c999a1bc61dd29b40fde313ee31475440be17c4d2d4d59e95b4229ed") == 2
    assert "No other lockfile change is approved" in report


def test_generation_a_contains_no_formal_or_private_artifact_candidate() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
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
        "cache/",
        "data/interim/",
        "data/processed/",
        "data/raw/",
        "models/",
        "results/runs/",
        "results/released/v0.6.0/",
    )
    violations = [
        path
        for path in candidates
        if (path.endswith(forbidden_suffixes) or path.startswith(forbidden_prefixes))
        and path != "cache/.gitkeep"
    ]
    assert violations == []
    assert "docs/attestations/v0.6.0-analysis-freeze.yaml" not in candidates
    assert all(not path.startswith("docs/plans/") for path in candidates)


def test_analysis_package_has_no_model_inference_or_sequence_loader_import() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "src/protein_split_audit/analysis").glob("*.py"))
    )
    forbidden_imports = (
        "protein_split_audit.models",
        "protein_split_audit.features",
        "protein_split_audit.embeddings",
        "protein_split_audit.similarity.mmseqs",
        "transformers",
        "torch",
        "httpx",
    )
    assert all(value not in source for value in forbidden_imports)
