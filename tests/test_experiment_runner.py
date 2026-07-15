# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from tests.v030_helpers import write_tiny_experiment

PROJECT_ROOT = Path(__file__).parents[1]


def test_validation_matrix_runs_exactly_twenty_cells_offline(tmp_path: Path) -> None:
    from protein_split_audit.experiments.matrix import run_matrix

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    result = run_matrix(
        experiment.config,
        nearest_hits_by_split={
            name: () for name in ("random", "cluster70", "cluster50", "cluster30")
        },
    )

    assert len(result.cells) == 20
    assert all(cell.evaluation_split == "validation" for cell in result.cells)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["cell_count"] == 20
    assert summary["evaluation_split"] == "validation"
    assert not any(path.name.startswith("test") for path in experiment.output_root.rglob("*"))


def test_existing_complete_matrix_is_not_overwritten(tmp_path: Path) -> None:
    from protein_split_audit.experiments.matrix import run_matrix

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    hits = {name: () for name in ("random", "cluster70", "cluster50", "cluster30")}
    run_matrix(experiment.config, nearest_hits_by_split=hits)

    try:
        run_matrix(experiment.config, nearest_hits_by_split=hits)
    except FileExistsError:
        pass
    else:
        raise AssertionError("completed matrix must not be overwritten")


def test_cell_writes_protocol_artifact_set_and_nearest_detail(tmp_path: Path) -> None:
    from protein_split_audit.experiments.runner import run_experiment_cell

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    cell = run_experiment_cell(
        experiment.config,
        "random",
        "nearest_homolog",
        nearest_hits=(),
    )

    assert cell.run_dir.name.startswith("tiny-v030-validation__random__nearest_homolog__seed42__")
    assert (cell.run_dir / "environment.json").is_file()
    assert (cell.run_dir / "run.log").is_file()
    nearest = pq.read_table(cell.run_dir / "nearest_homolog.parquet").to_pylist()
    assert [row["query_accession"] for row in nearest] == ["V0", "V1"]
    assert all(row["no_hit"] is True for row in nearest)


def test_matrix_resume_verifies_and_reuses_complete_cells(tmp_path: Path) -> None:
    from protein_split_audit.experiments.matrix import run_matrix

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    hits = {name: () for name in ("random", "cluster70", "cluster50", "cluster30")}
    first = run_matrix(experiment.config, nearest_hits_by_split=hits)
    second = run_matrix(experiment.config, nearest_hits_by_split=hits, resume=True)

    assert len(second.cells) == 20
    assert second.summary_path.read_bytes() == first.summary_path.read_bytes()


def test_matrix_resume_rejects_tampered_complete_cell(tmp_path: Path) -> None:
    from protein_split_audit.experiments.matrix import run_matrix

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    hits = {name: () for name in ("random", "cluster70", "cluster50", "cluster30")}
    first = run_matrix(experiment.config, nearest_hits_by_split=hits)
    (first.cells[0].run_dir / "metrics.json").write_text("{}\n", encoding="utf-8")

    try:
        run_matrix(experiment.config, nearest_hits_by_split=hits, resume=True)
    except ValueError as error:
        assert "completed run artifact hash mismatch" in str(error)
    else:
        raise AssertionError("resume must reject a tampered completed cell")
