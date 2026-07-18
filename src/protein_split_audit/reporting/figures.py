# SPDX-License-Identifier: Apache-2.0

"""Fixed-layout PDF figures for reviewed v0.6 aggregate CSV files."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.axes import Axes

from protein_split_audit.analysis.binning import IDENTITY_BINS, LENGTH_BINS
from protein_split_audit.analysis.schemas import LABEL_ORDER, METHODS, SPLITS

FIGURE_FILENAMES = (
    "generalization_gap.pdf",
    "macro_f1_by_split.pdf",
    "nearest_homolog_analysis.pdf",
    "per_class_gap.pdf",
    "performance_by_identity.pdf",
    "performance_by_length.pdf",
)
_FIGURE_SOURCES = {
    "macro_f1_by_split.pdf": "split_performance_summary.csv",
    "generalization_gap.pdf": "split_performance_summary.csv",
    "performance_by_identity.pdf": "identity_bin_summary.csv",
    "performance_by_length.pdf": "length_bin_summary.csv",
    "per_class_gap.pdf": "class_error_summary.csv",
    "nearest_homolog_analysis.pdf": "nearest_homolog_summary.csv",
}
_METHOD_LABELS = {
    "majority": "Majority",
    "length-logistic": "Length",
    "aac-logistic": "AAC",
    "kmer3-logistic": "3-mer",
    "nearest-homolog": "Nearest",
    "esm2-35m": "ESM2-35M",
    "esm2-150m": "ESM2-150M",
}
_SPLIT_LABELS = {
    "random": "Random",
    "cluster70": "Cluster70",
    "cluster50": "Cluster50",
    "cluster30": "Cluster30",
}
_IDENTITY_LABELS = {
    "identity_00_20": "0-20%",
    "identity_20_30": "20-30%",
    "identity_30_40": "30-40%",
    "identity_40_50": "40-50%",
    "identity_50_70": "50-70%",
    "identity_70_100": "70-100%",
    "no_hit": "No hit",
}
_LENGTH_LABELS = {
    "length_050_199": "50-199",
    "length_200_399": "200-399",
    "length_400_599": "400-599",
    "length_600_799": "600-799",
    "length_800_1000": "800-1000",
}
_PALETTE = (
    "#4E79A7",
    "#F28E2B",
    "#59A14F",
    "#E15759",
    "#B07AA1",
    "#76B7B2",
    "#EDC948",
)
_POINT_STATUSES = {"reportable", "insufficient_components_for_ci"}


@dataclass(frozen=True, slots=True)
class FigureSeries:
    """One deterministic public series within a panel."""

    label: str
    values: tuple[float | None, ...]
    lower: tuple[float | None, ...]
    upper: tuple[float | None, ...]
    color: str


@dataclass(frozen=True, slots=True)
class FigurePanel:
    """One fixed comparison panel with compatible measurement units."""

    title: str
    categories: tuple[str, ...]
    series: tuple[FigureSeries, ...]
    ylabel: str
    y_limits: tuple[float, float] | None = None
    zero_line: bool = False
    show_legend: bool = False
    legend_location: LegendLocation = "best"
    legend_anchor: tuple[float, float] | None = None
    legend_columns: int = 1
    color_by_category: bool = False
    tick_rotation: float = 0.0


@dataclass(frozen=True, slots=True)
class FigureSpec:
    """Complete deterministic layout for one public PDF."""

    title: str
    layout: tuple[int, int]
    figsize: tuple[float, float]
    panels: tuple[FigurePanel, ...]
    note: str
    shared_legend: bool = False
    bottom_margin: float | None = None


type CsvRow = dict[str, str]
type LegendLocation = Literal["best", "upper left", "lower left", "upper center"]


def _read_rows(path: Path) -> tuple[CsvRow, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _number(row: CsvRow | None, key: str) -> float | None:
    if row is None or row.get("reporting_status") not in _POINT_STATUSES:
        return None
    raw = row.get(key)
    if raw in {None, "", "NA"}:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"figure value is not finite: {key}")
    return value


def _index(rows: tuple[CsvRow, ...], key: str) -> dict[str, CsvRow]:
    indexed: dict[str, CsvRow] = {}
    for row in rows:
        identity = row.get(key)
        if identity in {None, "", "NA"}:
            continue
        if identity in indexed:
            raise ValueError(f"figure source has duplicate {key}: {identity}")
        indexed[identity] = row
    return indexed


def _series(
    label: str,
    color: str,
    rows: tuple[CsvRow, ...],
    category_key: str,
    categories: tuple[str, ...],
    value_key: str,
    lower_key: str,
    upper_key: str,
) -> FigureSeries:
    indexed = _index(rows, category_key)
    selected = tuple(indexed.get(category) for category in categories)
    return FigureSeries(
        label=label,
        values=tuple(_number(row, value_key) for row in selected),
        lower=tuple(_number(row, lower_key) for row in selected),
        upper=tuple(_number(row, upper_key) for row in selected),
        color=color,
    )


def _method_panel(
    rows: tuple[CsvRow, ...],
    *,
    title: str,
    value_key: str,
    lower_key: str,
    upper_key: str,
    ylabel: str,
    y_limits: tuple[float, float] | None,
    zero_line: bool,
) -> FigurePanel:
    series = _series(
        "Estimate",
        _PALETTE[0],
        rows,
        "method",
        METHODS,
        value_key,
        lower_key,
        upper_key,
    )
    return FigurePanel(
        title=title,
        categories=tuple(_METHOD_LABELS[method] for method in METHODS),
        series=(series,),
        ylabel=ylabel,
        y_limits=y_limits,
        zero_line=zero_line,
        color_by_category=True,
        tick_rotation=22.0,
    )


def _split_performance_specs(rows: tuple[CsvRow, ...]) -> tuple[FigureSpec, FigureSpec]:
    point_panels: list[FigurePanel] = []
    for split in SPLITS:
        selected = tuple(
            row
            for row in rows
            if row.get("metric") == "macro_f1" and row.get("split_name") == split
        )
        point_panels.append(
            _method_panel(
                selected,
                title=_SPLIT_LABELS[split],
                value_key="estimate",
                lower_key="ci_lower",
                upper_key="ci_upper",
                ylabel="Macro-F1",
                y_limits=(0.0, 1.0),
                zero_line=False,
            )
        )
    performance = FigureSpec(
        title="Macro-F1 by split",
        layout=(2, 2),
        figsize=(11.2, 7.2),
        panels=tuple(point_panels),
        note="Bars show point estimates; whiskers show 95% component-bootstrap intervals.",
    )

    gap_panels: list[FigurePanel] = []
    for split in SPLITS[1:]:
        selected = tuple(
            row
            for row in rows
            if row.get("metric") == "macro_f1" and row.get("comparison_split") == split
        )
        gap_panels.append(
            _method_panel(
                selected,
                title=f"Random - {_SPLIT_LABELS[split]}",
                value_key="difference",
                lower_key="difference_ci_lower",
                upper_key="difference_ci_upper",
                ylabel="Macro-F1 difference",
                y_limits=None,
                zero_line=True,
            )
        )
    gaps = FigureSpec(
        title="Random-minus-cluster Macro-F1 gaps",
        layout=(1, 3),
        figsize=(12.0, 4.5),
        panels=tuple(gap_panels),
        note="Positive values favor Random. Whiskers are independently resampled 95% intervals.",
    )
    return performance, gaps


def _stratified_spec(
    rows: tuple[CsvRow, ...],
    *,
    title: str,
    category_ids: tuple[str, ...],
    category_labels: tuple[str, ...],
    category_key: str,
) -> FigureSpec:
    panels: list[FigurePanel] = []
    for split in SPLITS:
        method_series = tuple(
            _series(
                _METHOD_LABELS[method],
                _PALETTE[method_order],
                tuple(
                    row
                    for row in rows
                    if row.get("split_name") == split
                    and row.get("method") == method
                    and row.get("metric") == "accuracy"
                ),
                category_key,
                category_ids,
                "estimate",
                "ci_lower",
                "ci_upper",
            )
            for method_order, method in enumerate(METHODS)
        )
        panels.append(
            FigurePanel(
                title=_SPLIT_LABELS[split],
                categories=category_labels,
                series=method_series,
                ylabel="Accuracy",
                y_limits=(0.0, 1.0),
                tick_rotation=18.0,
            )
        )
    return FigureSpec(
        title=title,
        layout=(2, 2),
        figsize=(11.6, 7.4),
        panels=tuple(panels),
        note=(
            "Suppressed or under-supported groups are omitted; no missing value is plotted as zero."
        ),
        shared_legend=True,
    )


def _class_gap_spec(rows: tuple[CsvRow, ...]) -> FigureSpec:
    method_series = tuple(
        _series(
            _METHOD_LABELS[method],
            _PALETTE[method_order],
            tuple(
                row
                for row in rows
                if row.get("split_name") == "cluster30" and row.get("method") == method
            ),
            "ec_level_2",
            LABEL_ORDER,
            "random_minus_cluster30_class_f1",
            "gap_ci_lower",
            "gap_ci_upper",
        )
        for method_order, method in enumerate(METHODS)
    )
    panel = FigurePanel(
        title="Random - Cluster30",
        categories=LABEL_ORDER,
        series=method_series,
        ylabel="Class F1 difference",
        zero_line=True,
    )
    return FigureSpec(
        title="Per-class generalization gap",
        layout=(1, 1),
        figsize=(10.8, 5.4),
        panels=(panel,),
        note=(
            "Suppressed or under-supported classes are omitted; "
            "whiskers show eligible 95% intervals."
        ),
        shared_legend=True,
    )


def _measure_series(
    rows: tuple[CsvRow, ...],
    measure: str,
    label: str,
    color: str,
    *,
    stratum_id: str = "whole_test",
) -> FigureSeries:
    selected = tuple(
        row for row in rows if row.get("measure") == measure and row.get("stratum_id") == stratum_id
    )
    return _series(
        label,
        color,
        selected,
        "split_name",
        SPLITS,
        "estimate",
        "ci_lower",
        "ci_upper",
    )


def _derived_rate_series(
    rows: tuple[CsvRow, ...],
    measure: str,
    label: str,
    color: str,
) -> FigureSeries:
    indexed = _index(
        tuple(
            row
            for row in rows
            if row.get("measure") == measure and row.get("stratum_id") == "whole_test"
        ),
        "split_name",
    )
    values: list[float | None] = []
    for split in SPLITS:
        row = indexed.get(split)
        count = _number(row, "estimate")
        total = _number(row, "sequence_count")
        values.append(None if count is None or total in {None, 0.0} else count / total)
    empty = (None,) * len(SPLITS)
    return FigureSeries(label, tuple(values), empty, empty, color)


def _nearest_homolog_spec(rows: tuple[CsvRow, ...]) -> FigureSpec:
    split_labels = tuple(_SPLIT_LABELS[split] for split in SPLITS)
    count_panel = FigurePanel(
        title="Hit and fallback counts",
        categories=split_labels,
        series=(
            _measure_series(rows, "hit_count", "Hit", _PALETTE[0]),
            _measure_series(rows, "no_hit_count", "No hit", _PALETTE[1]),
            _measure_series(rows, "fallback_count", "Fallback", _PALETTE[2]),
        ),
        ylabel="Sequences",
        y_limits=(0.0, 70.0),
        show_legend=True,
        legend_location="upper left",
    )
    fallback_panel = FigurePanel(
        title="No-hit fallback behavior",
        categories=split_labels,
        series=(
            _derived_rate_series(rows, "no_hit_count", "No-hit rate", _PALETTE[1]),
            _measure_series(rows, "no_hit_accuracy", "No-hit accuracy", _PALETTE[3]),
        ),
        ylabel="Fraction / accuracy",
        y_limits=(0.0, 1.0),
        show_legend=True,
        legend_location="upper left",
    )
    quality_panel = FigurePanel(
        title="Hit identity and coverage",
        categories=split_labels,
        series=(
            _measure_series(rows, "identity_mean", "Mean identity", _PALETTE[0]),
            _measure_series(rows, "query_coverage_mean", "Query coverage", _PALETTE[4]),
            _measure_series(rows, "target_coverage_mean", "Target coverage", _PALETTE[5]),
        ),
        ylabel="Identity / coverage",
        y_limits=(0.0, 1.0),
        show_legend=True,
        legend_location="upper center",
        legend_anchor=(0.5, -0.18),
        legend_columns=3,
    )
    difference_panel = FigurePanel(
        title="ESM2-150M - Nearest (no hit)",
        categories=split_labels,
        series=(
            _measure_series(
                rows,
                "accuracy_difference_esm2_150m_minus_nearest_homolog",
                "Accuracy difference",
                _PALETTE[6],
                stratum_id="no_hit",
            ),
        ),
        ylabel="Accuracy difference",
        zero_line=True,
    )
    return FigureSpec(
        title="Nearest Homolog analysis",
        layout=(2, 2),
        figsize=(11.2, 7.2),
        panels=(count_panel, fallback_panel, quality_panel, difference_panel),
        note=(
            "Bitscore and additional hit summaries remain available "
            "in the released aggregate table."
        ),
        bottom_margin=0.18,
    )


def build_figure_specs(aggregate_dir: Path) -> dict[str, FigureSpec]:
    """Build six fixed, result-independent presentation layouts from public CSV rows."""

    source_root = aggregate_dir.resolve()
    sources: dict[str, tuple[CsvRow, ...]] = {}
    for source_name in set(_FIGURE_SOURCES.values()):
        source = source_root / source_name
        if not source.is_file():
            raise FileNotFoundError(f"required aggregate table is missing: {source_name}")
        sources[source_name] = _read_rows(source)

    performance, gaps = _split_performance_specs(sources["split_performance_summary.csv"])
    identity_ids = tuple(item.id for item in IDENTITY_BINS)
    length_ids = tuple(item.id for item in LENGTH_BINS)
    specs = {
        "generalization_gap.pdf": gaps,
        "macro_f1_by_split.pdf": performance,
        "nearest_homolog_analysis.pdf": _nearest_homolog_spec(
            sources["nearest_homolog_summary.csv"]
        ),
        "per_class_gap.pdf": _class_gap_spec(sources["class_error_summary.csv"]),
        "performance_by_identity.pdf": _stratified_spec(
            sources["identity_bin_summary.csv"],
            title="Accuracy by nearest-Train identity",
            category_ids=identity_ids,
            category_labels=tuple(_IDENTITY_LABELS[item] for item in identity_ids),
            category_key="stratum_id",
        ),
        "performance_by_length.pdf": _stratified_spec(
            sources["length_bin_summary.csv"],
            title="Accuracy by sequence length",
            category_ids=length_ids,
            category_labels=tuple(_LENGTH_LABELS[item] for item in length_ids),
            category_key="stratum_id",
        ),
    }
    return {filename: specs[filename] for filename in FIGURE_FILENAMES}


def _render_panel(axis: Axes, panel: FigurePanel) -> None:
    category_count = len(panel.categories)
    series_count = max(1, len(panel.series))
    group_width = 0.8
    width = group_width / series_count
    positions = tuple(float(index) for index in range(category_count))
    has_value = False
    for series_order, series in enumerate(panel.series):
        offset = (series_order - (series_count - 1) / 2.0) * width
        bar_positions = tuple(position + offset for position in positions)
        plotted = tuple(math.nan if value is None else value for value in series.values)
        has_value = has_value or any(value is not None for value in series.values)
        lower_errors = tuple(
            0.0 if value is None or lower is None else max(0.0, value - lower)
            for value, lower in zip(series.values, series.lower, strict=True)
        )
        upper_errors = tuple(
            0.0 if value is None or upper is None else max(0.0, upper - value)
            for value, upper in zip(series.values, series.upper, strict=True)
        )
        has_interval = any(error > 0.0 for error in (*lower_errors, *upper_errors))
        colors: str | tuple[str, ...]
        if panel.color_by_category and len(panel.series) == 1:
            colors = _PALETTE[:category_count]
        else:
            colors = series.color
        axis.bar(
            bar_positions,
            plotted,
            width=width * 0.92,
            color=colors,
            edgecolor="#222222",
            linewidth=0.45,
            label=series.label,
            yerr=(lower_errors, upper_errors) if has_interval else None,
            capsize=2.0,
            error_kw={"elinewidth": 0.7, "capthick": 0.7},
        )
    axis.set_xticks(
        positions,
        panel.categories,
        rotation=panel.tick_rotation,
        ha="right" if panel.tick_rotation else "center",
    )
    axis.set_title(panel.title, fontsize=10, fontweight="bold")
    axis.set_ylabel(panel.ylabel)
    if panel.y_limits is not None:
        axis.set_ylim(*panel.y_limits)
    if panel.zero_line:
        axis.axhline(0.0, color="#333333", linewidth=0.8)
    axis.grid(axis="y", color="#dddddd", linewidth=0.55)
    axis.set_axisbelow(True)
    if not has_value:
        axis.text(
            0.5,
            0.5,
            "No reportable groups",
            ha="center",
            va="center",
            transform=axis.transAxes,
            color="#555555",
        )
    if panel.show_legend:
        axis.legend(
            frameon=False,
            fontsize=7,
            loc=panel.legend_location,
            bbox_to_anchor=panel.legend_anchor,
            ncol=panel.legend_columns,
        )


def _render_spec(spec: FigureSpec, destination: Path) -> None:
    with matplotlib.rc_context(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "pdf.compression": 9,
            "pdf.fonttype": 42,
        }
    ):
        rows, columns = spec.layout
        figure, axes = plt.subplots(
            rows,
            columns,
            figsize=spec.figsize,
            dpi=100,
            squeeze=False,
        )
        for panel, axis in zip(spec.panels, axes.flat, strict=False):
            _render_panel(axis, panel)
        for axis in tuple(axes.flat)[len(spec.panels) :]:
            axis.set_visible(False)
        bottom = (
            spec.bottom_margin
            if spec.bottom_margin is not None
            else 0.15
            if spec.shared_legend
            else 0.12
        )
        figure.subplots_adjust(
            left=0.075,
            right=0.985,
            bottom=bottom,
            top=0.88,
            hspace=0.42,
            wspace=0.27,
        )
        figure.suptitle(spec.title, fontsize=14, fontweight="bold")
        if spec.shared_legend and spec.panels:
            handles, labels = axes.flat[0].get_legend_handles_labels()
            figure.legend(
                handles,
                labels,
                loc="lower center",
                bbox_to_anchor=(0.5, 0.045),
                ncol=4,
                frameon=False,
                fontsize=8,
            )
        figure.text(0.5, 0.015, spec.note, ha="center", va="bottom", fontsize=7, color="#444444")
        figure.savefig(
            destination,
            format="pdf",
            metadata={
                "Title": spec.title,
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
    """Render six fixed figures from aggregate CSVs without overwriting."""

    destination = output_dir.resolve()
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing figure directory")
    specs = build_figure_specs(aggregate_dir)
    destination.mkdir(parents=True)
    outputs: list[Path] = []
    try:
        for filename in FIGURE_FILENAMES:
            output = destination / filename
            _render_spec(specs[filename], output)
            outputs.append(output)
    except BaseException:
        for path in outputs:
            path.unlink(missing_ok=True)
        destination.rmdir()
        raise
    return tuple(outputs)


__all__ = [
    "FIGURE_FILENAMES",
    "FigurePanel",
    "FigureSeries",
    "FigureSpec",
    "build_figure_specs",
    "render_release_figures",
]
