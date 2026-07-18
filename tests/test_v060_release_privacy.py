# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.analysis.schemas import PUBLIC_ARTIFACTS

PROJECT_ROOT = Path(__file__).parents[1]


def test_v060_public_allowlist_is_exact_and_aggregate_only() -> None:
    assert len(PUBLIC_ARTIFACTS) == 19
    assert len(set(PUBLIC_ARTIFACTS)) == 19
    assert sum(name.endswith(".csv") for name in PUBLIC_ARTIFACTS) == 10
    assert sum(name.endswith(".json") for name in PUBLIC_ARTIFACTS) == 2
    assert sum(name.endswith(".pdf") for name in PUBLIC_ARTIFACTS) == 6
    assert all(
        not name.endswith((".parquet", ".fasta", ".npy", ".joblib", ".jsonl", ".log"))
        for name in PUBLIC_ARTIFACTS
    )


def test_v060_private_run_and_exploratory_paths_remain_ignored() -> None:
    ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/results/runs/" in ignore
    assert "*.parquet" in ignore
    assert "*.joblib" in ignore
