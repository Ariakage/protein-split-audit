# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
from pathlib import Path

from tests.v030_helpers import write_tiny_experiment

PROJECT_ROOT = Path(__file__).parents[1]


def test_validation_aggregate_is_sorted_and_record_free(tmp_path: Path) -> None:
    from protein_split_audit.experiments.aggregate import write_validation_aggregates
    from protein_split_audit.experiments.matrix import run_matrix

    experiment = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    hits = {name: () for name in ("random", "cluster70", "cluster50", "cluster30")}
    run_matrix(experiment.config, nearest_hits_by_split=hits)
    output = tmp_path / "aggregate"

    result = write_validation_aggregates(experiment.output_root, output)

    with result.summary_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 20
    assert [(row["split"], row["baseline"]) for row in rows] == sorted(
        (row["split"], row["baseline"]) for row in rows
    )
    combined = b"".join(path.read_bytes() for path in result.paths)
    assert b"accession" not in combined
    assert b"sequence_sha256" not in combined
