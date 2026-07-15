# SPDX-License-Identifier: Apache-2.0

"""Deterministic five-by-four Validation matrix."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.runner import CellResult, run_experiment_cell
from protein_split_audit.models.nearest_homolog import HomologHit


@dataclass(frozen=True, slots=True)
class MatrixResult:
    """One complete Validation matrix."""

    cells: tuple[CellResult, ...]
    summary_path: Path


def run_matrix(
    config_path: Path,
    *,
    nearest_hits_by_split: dict[str, tuple[HomologHit, ...]] | None = None,
    resume: bool = False,
) -> MatrixResult:
    """Run exactly five baselines over four frozen splits."""

    config = load_experiment_config(config_path)
    if config.evaluation.split != "validation":
        raise ValueError("v0.3 matrix is Validation-only")
    summary_path = config.outputs.root / "matrix_summary.json"
    if summary_path.exists() and not resume:
        raise FileExistsError("completed Validation matrix already exists")
    cells: list[CellResult] = []
    for split in config.splits:
        for baseline in config.baselines:
            hits = (
                nearest_hits_by_split.get(split.name)
                if nearest_hits_by_split is not None and baseline.name == "nearest_homolog"
                else None
            )
            cells.append(
                run_experiment_cell(
                    config_path,
                    split.name,
                    baseline.name,
                    nearest_hits=hits,
                    resume=resume,
                )
            )
    payload = {
        "cell_count": len(cells),
        "evaluation_split": "validation",
        "cells": [
            {
                "baseline": cell.baseline_name,
                "balanced_accuracy": cell.metrics.balanced_accuracy,
                "macro_f1": cell.metrics.macro_f1,
                "run_identity": cell.run_dir.name.rsplit("__", maxsplit=1)[-1],
                "split": cell.split_name,
            }
            for cell in cells
        ],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if summary_path.exists():
        if summary_path.read_text(encoding="utf-8") != rendered:
            raise ValueError("completed Validation matrix summary mismatch")
    else:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(rendered, encoding="utf-8", newline="\n")
    return MatrixResult(tuple(cells), summary_path)


__all__ = ["MatrixResult", "run_matrix"]
