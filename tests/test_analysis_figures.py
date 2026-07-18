# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.analysis.aggregate import CSV_SCHEMAS, csv_bytes
from protein_split_audit.provenance import sha256_file
from protein_split_audit.reporting.figures import FIGURE_FILENAMES, render_release_figures


def _aggregate_tables(root: Path) -> None:
    root.mkdir()
    for filename, columns in CSV_SCHEMAS.items():
        row = {column: "NA" for column in columns}
        for key, value in {
            "schema_version": 1,
            "analysis_class": "confirmatory",
            "analysis_id": "synthetic",
            "split_order": 0,
            "split_name": "random",
            "stratum_order": 0,
            "stratum_id": "whole_test",
            "stratum_label": "Whole Test",
            "method_order": 0,
            "method": "majority",
            "metric_order": 0,
            "metric": "macro_f1",
            "estimate": 0.25,
            "difference": 0.05,
            "class_f1": 0.2,
            "measure": "accuracy",
            "reporting_status": "reportable",
        }.items():
            if key in row:
                row[key] = value
        (root / filename).write_bytes(
            csv_bytes(columns, (tuple(row[column] for column in columns),))
        )


def test_six_figures_are_byte_deterministic_and_sequence_free(tmp_path: Path) -> None:
    aggregate = tmp_path / "aggregate"
    _aggregate_tables(aggregate)
    first = tmp_path / "figures-a"
    second = tmp_path / "figures-b"

    render_release_figures(aggregate, first)
    render_release_figures(aggregate, second)

    assert tuple(path.name for path in sorted(first.iterdir())) == tuple(sorted(FIGURE_FILENAMES))
    assert {path.name: sha256_file(path) for path in first.iterdir()} == {
        path.name: sha256_file(path) for path in second.iterdir()
    }
    assert all(path.read_bytes().startswith(b"%PDF") for path in first.iterdir())
    assert all(b"/CreationDate" not in path.read_bytes() for path in first.iterdir())
