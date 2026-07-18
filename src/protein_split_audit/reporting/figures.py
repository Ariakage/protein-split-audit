# SPDX-License-Identifier: Apache-2.0

"""Fixed-layout PDF figures for reviewed v0.6 aggregate CSV files."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

FIGURE_FILENAMES = (
    "generalization_gap.pdf",
    "macro_f1_by_split.pdf",
    "nearest_homolog_analysis.pdf",
    "per_class_gap.pdf",
    "performance_by_identity.pdf",
    "performance_by_length.pdf",
)
_FIGURE_SOURCES = {
    "macro_f1_by_split.pdf": (
        "split_performance_summary.csv",
        "Macro-F1 by split",
        "estimate",
        {"metric": "macro_f1"},
    ),
    "generalization_gap.pdf": (
        "split_performance_summary.csv",
        "Random-minus-cluster gap",
        "difference",
        {"metric": "macro_f1"},
    ),
    "performance_by_identity.pdf": (
        "identity_bin_summary.csv",
        "Performance by identity",
        "estimate",
        {"metric": "accuracy"},
    ),
    "performance_by_length.pdf": (
        "length_bin_summary.csv",
        "Performance by length",
        "estimate",
        {"metric": "accuracy"},
    ),
    "per_class_gap.pdf": (
        "class_error_summary.csv",
        "Per-class generalization gap",
        "random_minus_cluster30_class_f1",
        {"split_name": "cluster30"},
    ),
    "nearest_homolog_analysis.pdf": (
        "nearest_homolog_summary.csv",
        "Nearest Homolog analysis",
        "estimate",
        {},
    ),
}
_PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00")


def _values(
    path: Path,
    *,
    value_key: str,
    filters: dict[str, str],
) -> tuple[list[str], list[float | None]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    labels: list[str] = []
    values: list[float | None] = []
    for index, row in enumerate(rows):
        if any(row.get(key) != value for key, value in filters.items()):
            continue
        label_parts = tuple(
            row[key]
            for key in (
                "split_name",
                "method",
                "stratum_label",
                "stratum_id",
                "ec_level_2",
                "measure",
            )
            if row.get(key) not in {None, "", "NA", "whole_test"}
        )
        raw = row.get(value_key)
        labels.append(" / ".join(label_parts) if label_parts else str(index + 1))
        values.append(float(raw) if raw not in {None, "", "NA"} else None)
    return labels, values


def _render(
    source: Path,
    destination: Path,
    title: str,
    value_key: str,
    filters: dict[str, str],
) -> None:
    labels, values = _values(source, value_key=value_key, filters=filters)
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "pdf.compression": 9,
            "pdf.fonttype": 42,
        }
    )
    figure, axis = plt.subplots(figsize=(6.4, 3.6), dpi=100)
    figure.subplots_adjust(left=0.1, right=0.98, bottom=0.38, top=0.88)
    if values:
        positions = list(range(len(values)))
        plotted = [0.0 if value is None else value for value in values]
        colors = [
            "#999999" if value is None else _PALETTE[index % len(_PALETTE)]
            for index, value in enumerate(values)
        ]
        axis.bar(positions, plotted, color=colors, width=0.72, linewidth=0.5, edgecolor="#222222")
        for index, value in enumerate(values):
            if value is None:
                axis.text(index, 0.0, "NA", ha="center", va="bottom")
        axis.set_xticks(positions, labels, rotation=35, ha="right")
    else:
        axis.text(0.5, 0.5, "NA", ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
    axis.axhline(0.0, color="#333333", linewidth=0.6)
    axis.set_title(title)
    axis.set_ylabel("Aggregate estimate")
    axis.grid(axis="y", color="#dddddd", linewidth=0.5)
    figure.savefig(
        destination,
        format="pdf",
        metadata={
            "Title": title,
            "Subject": "ProteinSplitAudit v0.6.0 confirmatory pilot aggregate",
            "Author": "ProteinSplitAudit",
            "Creator": "ProteinSplitAudit 0.6.0",
            "Producer": "ProteinSplitAudit 0.6.0",
            "CreationDate": None,
            "ModDate": None,
        },
    )
    plt.close(figure)


def render_release_figures(aggregate_dir: Path, output_dir: Path) -> tuple[Path, ...]:
    """Render the six fixed figures from aggregate CSVs without overwriting."""

    source_root = aggregate_dir.resolve()
    destination = output_dir.resolve()
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing figure directory")
    for source_name, _, _, _ in _FIGURE_SOURCES.values():
        source = source_root / source_name
        if not source.is_file():
            raise FileNotFoundError(f"required aggregate table is missing: {source_name}")
    destination.mkdir(parents=True)
    outputs: list[Path] = []
    try:
        for filename in FIGURE_FILENAMES:
            source_name, title, value_key, filters = _FIGURE_SOURCES[filename]
            output = destination / filename
            _render(source_root / source_name, output, title, value_key, filters)
            outputs.append(output)
    except BaseException:
        for path in outputs:
            path.unlink(missing_ok=True)
        destination.rmdir()
        raise
    return tuple(outputs)


__all__ = ["FIGURE_FILENAMES", "render_release_figures"]
