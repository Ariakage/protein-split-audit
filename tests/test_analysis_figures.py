# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import protein_split_audit.reporting.figures as figures
from protein_split_audit.analysis.aggregate import CSV_SCHEMAS, csv_bytes
from protein_split_audit.analysis.schemas import LABEL_ORDER, METHODS, SPLITS
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


def _write_rows(root: Path, filename: str, rows: list[dict[str, object]]) -> None:
    columns = CSV_SCHEMAS[filename]
    normalized = tuple(tuple(row.get(column, "NA") for column in columns) for row in rows)
    (root / filename).write_bytes(csv_bytes(columns, normalized))


def _presentation_tables(root: Path) -> None:
    root.mkdir()
    for filename, columns in CSV_SCHEMAS.items():
        (root / filename).write_bytes(csv_bytes(columns, ()))

    split_rows: list[dict[str, object]] = []
    for split_order, split in enumerate(SPLITS):
        for method_order, method in enumerate(METHODS):
            row: dict[str, object] = {
                "schema_version": 1,
                "analysis_class": "confirmatory",
                "analysis_id": "synthetic",
                "split_order": split_order,
                "split_name": split,
                "stratum_dimension": "whole_test",
                "stratum_order": 0,
                "stratum_id": "whole_test",
                "stratum_label": "Whole Test",
                "method_order": method_order,
                "method": method,
                "metric_order": 2,
                "metric": "macro_f1",
                "sequence_count_display": 30,
                "sequence_count": 30,
                "component_count_display": 20,
                "component_count": 20,
                "estimate": 0.2 + 0.05 * method_order,
                "ci_lower": 0.15 + 0.05 * method_order,
                "ci_upper": 0.25 + 0.05 * method_order,
                "bootstrap_iterations": 2000,
                "bootstrap_seed": 2026,
                "reporting_status": "reportable",
            }
            if split != "random":
                row.update(
                    {
                        "comparison_split": split,
                        "difference_direction": "random_minus_comparison",
                        "difference": 0.03,
                        "difference_ci_lower": -0.02,
                        "difference_ci_upper": 0.08,
                        "resampling": "independent_component_bootstrap",
                    }
                )
            split_rows.append(row)
    _write_rows(root, "split_performance_summary.csv", split_rows)

    identity_rows: list[dict[str, object]] = []
    length_rows: list[dict[str, object]] = []
    for split_order, split in enumerate(SPLITS):
        for method_order, method in enumerate(METHODS):
            common = {
                "schema_version": 1,
                "analysis_class": "confirmatory",
                "analysis_id": "synthetic",
                "split_order": split_order,
                "split_name": split,
                "method_order": method_order,
                "method": method,
                "metric_order": 0,
                "metric": "accuracy",
                "sequence_count_display": 30,
                "sequence_count": 30,
                "component_count_display": 20,
                "component_count": 20,
                "estimate": 0.4 + 0.03 * method_order,
                "ci_lower": 0.35 + 0.03 * method_order,
                "ci_upper": 0.45 + 0.03 * method_order,
                "bootstrap_iterations": 2000,
                "bootstrap_seed": 2026,
                "reporting_status": "reportable",
            }
            identity_rows.append(
                {
                    **common,
                    "stratum_dimension": "identity",
                    "stratum_order": 6,
                    "stratum_id": "no_hit",
                    "stratum_label": "No hit",
                }
            )
            length_rows.append(
                {
                    **common,
                    "stratum_dimension": "length",
                    "stratum_order": 1,
                    "stratum_id": "length_200_399",
                    "stratum_label": "200-399",
                }
            )
    _write_rows(root, "identity_bin_summary.csv", identity_rows)
    _write_rows(root, "length_bin_summary.csv", length_rows)

    class_rows = [
        {
            "schema_version": 1,
            "analysis_class": "confirmatory",
            "split_order": 3,
            "split_name": "cluster30",
            "method_order": method_order,
            "method": method,
            "label_order": 0,
            "ec_level_2": LABEL_ORDER[0],
            "sequence_count_display": 30,
            "sequence_count": 30,
            "component_count_display": 20,
            "component_count": 20,
            "random_minus_cluster30_class_f1": 0.02 * (method_order - 3),
            "gap_ci_lower": -0.1,
            "gap_ci_upper": 0.1,
            "reporting_status": "reportable",
        }
        for method_order, method in enumerate(METHODS)
    ]
    _write_rows(root, "class_error_summary.csv", class_rows)

    nearest_rows: list[dict[str, object]] = []
    measures = {
        "hit_count": 10.0,
        "no_hit_count": 56.0,
        "fallback_count": 56.0,
        "no_hit_accuracy": 0.45,
        "identity_mean": 0.31,
        "query_coverage_mean": 0.91,
        "target_coverage_mean": 0.89,
    }
    for split_order, split in enumerate(SPLITS):
        for measure_order, (measure, estimate) in enumerate(measures.items()):
            nearest_rows.append(
                {
                    "schema_version": 1,
                    "analysis_class": "confirmatory",
                    "split_order": split_order,
                    "split_name": split,
                    "stratum_order": 0,
                    "stratum_id": "whole_test",
                    "measure_order": measure_order,
                    "measure": measure,
                    "method_order": 4,
                    "method": "nearest-homolog",
                    "sequence_count_display": 66,
                    "sequence_count": 66,
                    "component_count_display": 60,
                    "component_count": 60,
                    "estimate": estimate,
                    "reporting_status": "reportable",
                }
            )
        nearest_rows.append(
            {
                "schema_version": 1,
                "analysis_class": "confirmatory",
                "split_order": split_order,
                "split_name": split,
                "stratum_order": 6,
                "stratum_id": "no_hit",
                "measure_order": 15,
                "measure": "accuracy_difference_esm2_150m_minus_nearest_homolog",
                "method_order": 4,
                "method": "nearest-homolog",
                "sequence_count_display": 56,
                "sequence_count": 56,
                "component_count_display": 50,
                "component_count": 50,
                "estimate": 0.3,
                "ci_lower": 0.15,
                "ci_upper": 0.45,
                "reporting_status": "reportable",
            }
        )
    _write_rows(root, "nearest_homolog_summary.csv", nearest_rows)


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


def test_presentation_specs_use_readable_facets_and_separate_units(tmp_path: Path) -> None:
    aggregate = tmp_path / "aggregate"
    _presentation_tables(aggregate)

    specs = figures.build_figure_specs(aggregate)

    assert tuple(specs) == FIGURE_FILENAMES
    assert specs["macro_f1_by_split.pdf"].layout == (2, 2)
    assert tuple(panel.title for panel in specs["macro_f1_by_split.pdf"].panels) == (
        "Random",
        "Cluster70",
        "Cluster50",
        "Cluster30",
    )
    assert specs["generalization_gap.pdf"].layout == (1, 3)
    assert tuple(panel.title for panel in specs["generalization_gap.pdf"].panels) == (
        "Random - Cluster70",
        "Random - Cluster50",
        "Random - Cluster30",
    )
    assert specs["performance_by_identity.pdf"].layout == (2, 2)
    assert specs["performance_by_identity.pdf"].panels[0].categories == (
        "0-20%",
        "20-30%",
        "30-40%",
        "40-50%",
        "50-70%",
        "70-100%",
        "No hit",
    )
    assert specs["performance_by_length.pdf"].panels[0].categories == (
        "50-199",
        "200-399",
        "400-599",
        "600-799",
        "800-1000",
    )
    assert specs["per_class_gap.pdf"].panels[0].categories == LABEL_ORDER
    assert tuple(panel.ylabel for panel in specs["nearest_homolog_analysis.pdf"].panels) == (
        "Sequences",
        "Fraction / accuracy",
        "Identity / coverage",
        "Accuracy difference",
    )
    assert tuple(
        panel.legend_location for panel in specs["nearest_homolog_analysis.pdf"].panels[:3]
    ) == ("upper left", "upper left", "upper center")
    quality_panel = specs["nearest_homolog_analysis.pdf"].panels[2]
    assert quality_panel.legend_anchor == (0.5, -0.18)
    assert quality_panel.legend_columns == 3
    assert specs["nearest_homolog_analysis.pdf"].bottom_margin == 0.18
    assert specs["nearest_homolog_analysis.pdf"].panels[0].y_limits == (0.0, 70.0)
    for spec in specs.values():
        for panel in spec.panels:
            assert all(
                "NA" not in category and "/" not in category for category in panel.categories
            )
            assert all(len(category) <= 12 for category in panel.categories)
