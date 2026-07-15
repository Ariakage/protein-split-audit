# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from tests.v030_helpers import write_tiny_experiment

PROJECT_ROOT = Path(__file__).parents[1]


def test_evaluate_run_verifies_completed_validation_artifacts(tmp_path: Path) -> None:
    from protein_split_audit.evaluation.standalone import verify_evaluation_run
    from protein_split_audit.experiments.runner import run_experiment_cell

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    cell = run_experiment_cell(experiment.config, "random", "majority")

    result = verify_evaluation_run(cell.run_dir)

    assert result.evaluation_split == "validation"
    assert result.artifact_count >= 5
    assert result.metrics_path == cell.run_dir / "metrics.json"
