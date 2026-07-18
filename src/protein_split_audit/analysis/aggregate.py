# SPDX-License-Identifier: Apache-2.0

"""Canonical aggregate serialization and no-clobber bundle writes."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from protein_split_audit import __version__
from protein_split_audit.analysis.binning import (
    COMPONENT_SIZE_BINS,
    IDENTITY_BINS,
    LENGTH_BINS,
    BinAssignment,
    component_size_bin,
    identity_bin,
    length_bin,
)
from protein_split_audit.analysis.inputs import AnalysisRow
from protein_split_audit.analysis.model_comparison import (
    RQ5_COMPARISONS,
    IndependentSplitGap,
    PairedMetricDifference,
    independent_split_gap,
    paired_metric_difference,
)
from protein_split_audit.analysis.nearest_homolog import summarize_nearest_homolog
from protein_split_audit.analysis.privacy import group_eligibility
from protein_split_audit.analysis.robustness import (
    AGREEMENT_PAIRS,
    component_influence,
    prediction_agreement,
    seed_diagnostic,
    sign_concordance,
)
from protein_split_audit.analysis.schemas import (
    LABEL_ORDER,
    METHODS,
    PUBLIC_ARTIFACTS,
    SPLITS,
    AnalysisSession,
    MetricName,
)
from protein_split_audit.analysis.stratified_metrics import (
    AggregateMetric,
    aggregate_metric,
    class_error_metrics,
    summarize_strata,
)
from protein_split_audit.provenance import sha256_bytes
from protein_split_audit.publication import publish_bundle
from protein_split_audit.statistics.group_bootstrap import domain_group_bootstrap_indices

METRICS: tuple[MetricName, ...] = ("accuracy", "balanced_accuracy", "macro_f1")

SHARED_METRIC_COLUMNS = (
    "schema_version",
    "analysis_class",
    "analysis_id",
    "split_order",
    "split_name",
    "stratum_dimension",
    "stratum_order",
    "stratum_id",
    "stratum_label",
    "method_order",
    "method",
    "metric_order",
    "metric",
    "sequence_count_display",
    "sequence_count",
    "component_count_display",
    "component_count",
    "estimate",
    "ci_lower",
    "ci_upper",
    "bootstrap_iterations",
    "bootstrap_seed",
    "reporting_status",
)
CSV_SCHEMAS: dict[str, tuple[str, ...]] = {
    "split_performance_summary.csv": (
        *SHARED_METRIC_COLUMNS,
        "comparison_split",
        "difference_direction",
        "difference",
        "difference_ci_lower",
        "difference_ci_upper",
        "resampling",
    ),
    "identity_bin_summary.csv": SHARED_METRIC_COLUMNS,
    "length_bin_summary.csv": SHARED_METRIC_COLUMNS,
    "component_size_summary.csv": SHARED_METRIC_COLUMNS,
    "class_error_summary.csv": (
        "schema_version",
        "analysis_class",
        "split_order",
        "split_name",
        "method_order",
        "method",
        "label_order",
        "ec_level_2",
        "sequence_count_display",
        "sequence_count",
        "component_count_display",
        "component_count",
        "class_precision",
        "class_recall",
        "class_f1",
        "class_f1_ci_lower",
        "class_f1_ci_upper",
        "dominant_wrong_label",
        "dominant_wrong_count",
        "random_minus_cluster30_class_f1",
        "gap_ci_lower",
        "gap_ci_upper",
        "reporting_status",
    ),
    "nearest_homolog_summary.csv": (
        "schema_version",
        "analysis_class",
        "split_order",
        "split_name",
        "stratum_order",
        "stratum_id",
        "measure_order",
        "measure",
        "method_order",
        "method",
        "sequence_count_display",
        "sequence_count",
        "component_count_display",
        "component_count",
        "estimate",
        "ci_lower",
        "ci_upper",
        "reporting_status",
    ),
    "model_comparisons.csv": (
        "schema_version",
        "analysis_class",
        "dimension_order",
        "dimension",
        "stratum_order",
        "stratum_id",
        "split_order",
        "split_name",
        "comparison_order",
        "method_a",
        "method_b",
        "metric_order",
        "metric",
        "point_a",
        "point_b",
        "difference_method_a_minus_method_b",
        "ci_lower",
        "ci_upper",
        "sequence_count_display",
        "sequence_count",
        "component_count_display",
        "component_count",
        "bootstrap_seed",
        "reporting_status",
    ),
    "prediction_agreement.csv": (
        "schema_version",
        "analysis_class",
        "split_order",
        "split_name",
        "comparison_order",
        "method_a",
        "method_b",
        "both_correct",
        "both_wrong",
        "method_a_only_correct",
        "method_b_only_correct",
        "both_correct_fraction",
        "both_wrong_fraction",
        "method_a_only_correct_fraction",
        "method_b_only_correct_fraction",
        "sequence_count_display",
        "sequence_count",
        "component_count_display",
        "component_count",
        "reporting_status",
    ),
    "component_influence.csv": (
        "schema_version",
        "analysis_class",
        "split_order",
        "split_name",
        "method_order",
        "method",
        "metric_order",
        "metric",
        "removal_order",
        "removal_count",
        "removed_sequence_count",
        "remaining_sequence_count_display",
        "remaining_sequence_count",
        "remaining_component_count_display",
        "remaining_component_count",
        "estimate",
        "ci_lower",
        "ci_upper",
        "reporting_status",
    ),
    "robustness_summary.csv": (
        "schema_version",
        "analysis_class",
        "diagnostic_order",
        "diagnostic",
        "split_order",
        "split_name",
        "method_a",
        "method_b",
        "metric_order",
        "metric",
        "accuracy_difference",
        "balanced_accuracy_difference",
        "macro_f1_difference",
        "signs_agree",
        "direction",
        "primary_seed",
        "diagnostic_seed",
        "maximum_lower_shift",
        "maximum_upper_shift",
        "maximum_width_shift",
        "reporting_status",
    ),
}


@dataclass(frozen=True, slots=True)
class DeterministicBundleResult:
    """Hashes of a newly written deterministic output bundle."""

    root: Path
    file_sha256: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    """One newly written formal analysis session."""

    session: AnalysisSession
    output_dir: Path
    deterministic_file_sha256: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AnalysisAggregateResult:
    """One replay-authorized aggregate review bundle before figures."""

    output_dir: Path
    file_sha256: Mapping[str, str]


def _format_csv_value(value: object) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("aggregate CSV values must be finite")
        if value == 0.0:
            return "0"
        rendered = f"{value:.15f}".rstrip("0").rstrip(".")
        return rendered if rendered not in {"", "-0"} else "0"
    return str(value)


def csv_bytes(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> bytes:
    """Serialize RFC-compatible UTF-8 CSV with fixed LF and NA spelling."""

    header = tuple(columns)
    if not header or len(set(header)) != len(header):
        raise ValueError("aggregate CSV columns must be nonempty and unique")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        values = tuple(row)
        if len(values) != len(header):
            raise ValueError("aggregate CSV row width differs from its schema")
        writer.writerow(tuple(_format_csv_value(value) for value in values))
    return buffer.getvalue().encode("utf-8")


def _normalize_json(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("aggregate JSON values must be finite")
        return 0.0 if value == 0.0 else value
    if isinstance(value, dict):
        return {str(key): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    return value


def json_bytes(value: object) -> bytes:
    """Serialize sorted, timestamp-free deterministic JSON."""

    return (
        json.dumps(
            _normalize_json(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_deterministic_bundle(
    root: Path,
    outputs: Mapping[str, bytes],
) -> DeterministicBundleResult:
    """Write one complete bundle without replacing any prior artifact."""

    destination = root.resolve()
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing analysis output")
    normalized = tuple(sorted(outputs.items()))
    if not normalized:
        raise ValueError("analysis output bundle cannot be empty")
    for name, _ in normalized:
        logical = Path(name)
        if logical.is_absolute() or ".." in logical.parts or logical.as_posix() != name:
            raise ValueError("analysis output names must be normalized relative paths")
    publish_bundle({destination / name: content for name, content in normalized})
    (destination / ".psaudit-publication.lock").unlink(missing_ok=True)
    hashes = {name: sha256_bytes(content) for name, content in normalized}
    return DeterministicBundleResult(destination, hashes)


def _cell_rows(
    rows: Sequence[AnalysisRow],
    *,
    strict_row_count: bool,
) -> dict[tuple[str, str], tuple[AnalysisRow, ...]]:
    records = tuple(rows)
    cells: dict[tuple[str, str], tuple[AnalysisRow, ...]] = {}
    for split in SPLITS:
        reference: tuple[tuple[object, ...], ...] | None = None
        for method in METHODS:
            members = tuple(
                sorted(
                    (row for row in records if row.split_name == split and row.method == method),
                    key=lambda row: (row.accession, row.sequence_sha256),
                )
            )
            if not members or (strict_row_count and len(members) != 66):
                raise ValueError("analysis row inventory is incomplete")
            identity = tuple(
                (
                    row.accession,
                    row.sequence_sha256,
                    row.true_label,
                    row.sequence_length,
                    row.component_id,
                    row.component_size,
                    row.nearest_train_identity,
                    row.no_hit,
                )
                for row in members
            )
            if reference is None:
                reference = identity
            elif identity != reference:
                raise ValueError("analysis methods do not share an identical private inventory")
            cells[(split, method)] = members
    if len(records) != sum(len(value) for value in cells.values()):
        raise ValueError("analysis rows contain an unapproved method or split")
    return cells


def _shared_values(
    item: AggregateMetric,
    *,
    split_order: int,
    split: str,
    method_order: int,
    method: str,
) -> tuple[object, ...]:
    eligibility = item.eligibility
    return (
        1,
        "confirmatory",
        item.analysis_id,
        split_order,
        split,
        item.stratum_dimension,
        item.stratum_order,
        item.stratum_id,
        item.stratum_label,
        method_order,
        method,
        METRICS.index(item.metric),
        item.metric,
        eligibility.sequence_count_display,
        eligibility.public_sequence_count,
        eligibility.component_count_display,
        eligibility.public_component_count,
        item.estimate,
        item.ci_lower,
        item.ci_upper,
        2000 if item.bootstrap_seed is not None else None,
        item.bootstrap_seed,
        eligibility.reporting_status,
    )


def _whole_metric(rows: tuple[AnalysisRow, ...], metric: MetricName) -> AggregateMetric:
    return aggregate_metric(
        rows,
        dimension="whole_test",
        stratum=BinAssignment(0, "whole_test", "Whole Test"),
        metric=metric,
    )


def _split_performance(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    rows: list[tuple[object, ...]] = []
    gaps: dict[tuple[str, str, MetricName], IndependentSplitGap] = {}
    for method in METHODS:
        for comparison in SPLITS[1:]:
            for metric in METRICS:
                gaps[(method, comparison, metric)] = independent_split_gap(
                    cells[("random", method)],
                    cells[(comparison, method)],
                    metric=metric,
                )
    for split_order, split in enumerate(SPLITS):
        for method_order, method in enumerate(METHODS):
            for metric in METRICS:
                item = _whole_metric(cells[(split, method)], metric)
                shared = _shared_values(
                    item,
                    split_order=split_order,
                    split=split,
                    method_order=method_order,
                    method=method,
                )
                if split == "random":
                    extra: tuple[object, ...] = (None, None, None, None, None, None)
                else:
                    gap = gaps[(method, split, metric)]
                    extra = (
                        split,
                        gap.direction,
                        gap.point_difference,
                        gap.ci_lower,
                        gap.ci_upper,
                        gap.resampling,
                    )
                rows.append(shared + extra)
    return csv_bytes(CSV_SCHEMAS["split_performance_summary.csv"], rows)


def _stratified_table(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
    *,
    dimension: str,
    filename: str,
) -> bytes:
    rows: list[tuple[object, ...]] = []
    for split_order, split in enumerate(SPLITS):
        for method_order, method in enumerate(METHODS):
            summary = summarize_strata(
                cells[(split, method)],
                dimension=dimension,
                include_empty=True,
            )
            rows.extend(
                _shared_values(
                    item,
                    split_order=split_order,
                    split=split,
                    method_order=method_order,
                    method=method,
                )
                for item in summary
            )
    return csv_bytes(CSV_SCHEMAS[filename], rows)


def _class_errors(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    def class_f1(records: tuple[AnalysisRow, ...], label: str) -> float:
        return class_error_metrics(records)[LABEL_ORDER.index(label)].f1

    def class_interval(
        records: tuple[AnalysisRow, ...],
        label: str,
        *,
        domain: str,
    ) -> tuple[float, float]:
        draws = domain_group_bootstrap_indices(
            tuple(row.component_id for row in records),
            iterations=2000,
            seed=2026,
            domain=domain,
        )
        values = np.asarray(
            [class_f1(tuple(records[int(index)] for index in draw), label) for draw in draws],
            dtype=np.float64,
        )
        lower, upper = np.quantile(values, [0.025, 0.975], method="linear")
        return float(lower), float(upper)

    gaps: dict[tuple[str, str], tuple[float | None, float | None, float | None]] = {}
    for method in METHODS:
        for label in LABEL_ORDER:
            random_records = cells[("random", method)]
            cluster_records = cells[("cluster30", method)]
            random_members = tuple(row for row in random_records if row.true_label == label)
            cluster_members = tuple(row for row in cluster_records if row.true_label == label)
            random_eligibility = group_eligibility(
                len(random_members), len({row.component_id for row in random_members})
            )
            cluster_eligibility = group_eligibility(
                len(cluster_members), len({row.component_id for row in cluster_members})
            )
            if not (
                random_eligibility.point_metric_allowed and cluster_eligibility.point_metric_allowed
            ):
                gaps[(method, label)] = (None, None, None)
                continue
            point = class_f1(random_records, label) - class_f1(cluster_records, label)
            lower: float | None = None
            upper: float | None = None
            if random_eligibility.interval_allowed and cluster_eligibility.interval_allowed:
                root = f"v060:class-gap:{method}:{label}:2026"
                random_draws = domain_group_bootstrap_indices(
                    tuple(row.component_id for row in random_records),
                    iterations=2000,
                    seed=2026,
                    domain=f"{root}:random",
                )
                cluster_draws = domain_group_bootstrap_indices(
                    tuple(row.component_id for row in cluster_records),
                    iterations=2000,
                    seed=2026,
                    domain=f"{root}:cluster30",
                )
                estimates = np.asarray(
                    [
                        class_f1(
                            tuple(random_records[int(index)] for index in random_draw),
                            label,
                        )
                        - class_f1(
                            tuple(cluster_records[int(index)] for index in cluster_draw),
                            label,
                        )
                        for random_draw, cluster_draw in zip(
                            random_draws,
                            cluster_draws,
                            strict=True,
                        )
                    ],
                    dtype=np.float64,
                )
                lower_value, upper_value = np.quantile(
                    estimates,
                    [0.025, 0.975],
                    method="linear",
                )
                lower = float(lower_value)
                upper = float(upper_value)
            gaps[(method, label)] = (point, lower, upper)

    rows: list[tuple[object, ...]] = []
    for split_order, split in enumerate(SPLITS):
        for method_order, method in enumerate(METHODS):
            records = cells[(split, method)]
            metrics = class_error_metrics(records)
            for label_order, item in enumerate(metrics):
                members = tuple(row for row in records if row.true_label == item.label)
                eligibility = group_eligibility(
                    len(members), len({row.component_id for row in members})
                )
                point = eligibility.point_metric_allowed
                ci_lower: float | None = None
                ci_upper: float | None = None
                if eligibility.interval_allowed:
                    ci_lower, ci_upper = class_interval(
                        records,
                        item.label,
                        domain=f"v060:class:{split}:{method}:{item.label}:2026",
                    )
                gap, gap_lower, gap_upper = gaps[(method, item.label)]
                rows.append(
                    (
                        1,
                        "confirmatory",
                        split_order,
                        split,
                        method_order,
                        method,
                        label_order,
                        item.label,
                        eligibility.sequence_count_display,
                        eligibility.public_sequence_count,
                        eligibility.component_count_display,
                        eligibility.public_component_count,
                        item.precision if point else None,
                        item.recall if point else None,
                        item.f1 if point else None,
                        ci_lower,
                        ci_upper,
                        item.dominant_wrong_label if point else None,
                        item.dominant_wrong_count if point else None,
                        gap if split == "cluster30" else None,
                        gap_lower if split == "cluster30" else None,
                        gap_upper if split == "cluster30" else None,
                        eligibility.reporting_status,
                    )
                )
    return csv_bytes(CSV_SCHEMAS["class_error_summary.csv"], rows)


def _dimension_groups(
    rows: tuple[AnalysisRow, ...],
    dimension: str,
) -> tuple[tuple[int, str, tuple[AnalysisRow, ...]], ...]:
    if dimension == "whole_test":
        return ((0, "whole_test", rows),)
    if dimension == "identity":
        return tuple(
            (
                item.order,
                item.id,
                tuple(
                    row
                    for row in rows
                    if identity_bin(row.nearest_train_identity, no_hit=row.no_hit).id == item.id
                ),
            )
            for item in IDENTITY_BINS
        )
    if dimension == "length":
        return tuple(
            (
                item.order,
                item.id,
                tuple(row for row in rows if length_bin(row.sequence_length).id == item.id),
            )
            for item in LENGTH_BINS
        )
    if dimension == "ec_class":
        return tuple(
            (order, label, tuple(row for row in rows if row.true_label == label))
            for order, label in enumerate(LABEL_ORDER)
        )
    if dimension == "component_size":
        return tuple(
            (
                item.order,
                item.id,
                tuple(row for row in rows if component_size_bin(row.component_size).id == item.id),
            )
            for item in COMPONENT_SIZE_BINS
        )
    raise ValueError("unknown model-comparison dimension")


def _comparison_table(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    rows: list[tuple[object, ...]] = []
    dimensions = ("whole_test", "identity", "length", "ec_class", "component_size")
    for dimension_order, dimension in enumerate(dimensions):
        for split_order, split in enumerate(SPLITS):
            for comparison_order, (method_a, method_b) in enumerate(RQ5_COMPARISONS):
                first_groups = _dimension_groups(cells[(split, method_a)], dimension)
                second_groups = _dimension_groups(cells[(split, method_b)], dimension)
                for (stratum_order, stratum_id, first), (_, second_id, second) in zip(
                    first_groups,
                    second_groups,
                    strict=True,
                ):
                    if stratum_id != second_id:
                        raise ValueError("paired stratum identities differ")
                    eligibility = group_eligibility(
                        len(first), len({row.component_id for row in first})
                    )
                    for metric_order, metric in enumerate(METRICS):
                        if first:
                            result = paired_metric_difference(first, second, metric=metric)
                            point_a = result.point_a
                            point_b = result.point_b
                            difference = result.point_difference
                            lower = result.ci_lower
                            upper = result.ci_upper
                        else:
                            point_a = point_b = difference = lower = upper = None
                        rows.append(
                            (
                                1,
                                "confirmatory",
                                dimension_order,
                                dimension,
                                stratum_order,
                                stratum_id,
                                split_order,
                                split,
                                comparison_order,
                                method_a,
                                method_b,
                                metric_order,
                                metric,
                                point_a,
                                point_b,
                                difference,
                                lower,
                                upper,
                                eligibility.sequence_count_display,
                                eligibility.public_sequence_count,
                                eligibility.component_count_display,
                                eligibility.public_component_count,
                                2026 if eligibility.interval_allowed else None,
                                eligibility.reporting_status,
                            )
                        )
    return csv_bytes(CSV_SCHEMAS["model_comparisons.csv"], rows)


def _nearest_table(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    rows: list[tuple[object, ...]] = []
    measures = (
        "hit_count",
        "no_hit_count",
        "fallback_count",
        "no_hit_accuracy",
        "same_label_hit_count",
        "different_label_hit_count",
        "identity_min",
        "identity_median",
        "identity_mean",
        "identity_p90",
        "identity_p95",
        "identity_max",
        "query_coverage_mean",
        "target_coverage_mean",
        "bitscore_mean",
    )
    for split_order, split in enumerate(SPLITS):
        records = cells[(split, "nearest-homolog")]
        summary = summarize_nearest_homolog(records)
        eligibility = group_eligibility(len(records), len({row.component_id for row in records}))
        values: dict[str, object] = {
            "hit_count": summary.hit_count,
            "no_hit_count": summary.no_hit_count,
            "fallback_count": summary.fallback_count,
            "no_hit_accuracy": (
                summary.no_hit_correct_count / summary.no_hit_count
                if summary.no_hit_count
                else None
            ),
            "same_label_hit_count": summary.same_label_hit_count,
            "different_label_hit_count": summary.different_label_hit_count,
            "identity_min": summary.identity.minimum,
            "identity_median": summary.identity.median,
            "identity_mean": summary.identity.mean,
            "identity_p90": summary.identity.p90,
            "identity_p95": summary.identity.p95,
            "identity_max": summary.identity.maximum,
            "query_coverage_mean": summary.query_coverage.mean,
            "target_coverage_mean": summary.target_coverage.mean,
            "bitscore_mean": summary.bitscore.mean,
        }
        for measure_order, measure in enumerate(measures):
            rows.append(
                (
                    1,
                    "confirmatory",
                    split_order,
                    split,
                    0,
                    "whole_test",
                    measure_order,
                    measure,
                    METHODS.index("nearest-homolog"),
                    "nearest-homolog",
                    eligibility.sequence_count_display,
                    eligibility.public_sequence_count,
                    eligibility.component_count_display,
                    eligibility.public_component_count,
                    values[measure]
                    if eligibility.reporting_status != "privacy_suppressed"
                    else None,
                    None,
                    None,
                    eligibility.reporting_status,
                )
            )
        for method in ("nearest-homolog", "esm2-150m"):
            for item in summarize_strata(
                cells[(split, method)],
                dimension="identity",
                include_empty=True,
            ):
                if item.metric != "accuracy":
                    continue
                rows.append(
                    (
                        1,
                        "confirmatory",
                        split_order,
                        split,
                        item.stratum_order,
                        item.stratum_id,
                        len(measures),
                        "accuracy",
                        METHODS.index(method),
                        method,
                        item.eligibility.sequence_count_display,
                        item.eligibility.public_sequence_count,
                        item.eligibility.component_count_display,
                        item.eligibility.public_component_count,
                        item.estimate,
                        item.ci_lower,
                        item.ci_upper,
                        item.eligibility.reporting_status,
                    )
                )
        esm_groups = _dimension_groups(cells[(split, "esm2-150m")], "identity")
        nearest_groups = _dimension_groups(cells[(split, "nearest-homolog")], "identity")
        for (stratum_order, stratum_id, esm_rows), (_, nearest_id, nearest_rows) in zip(
            esm_groups,
            nearest_groups,
            strict=True,
        ):
            if stratum_id != nearest_id:
                raise ValueError("RQ6 identity strata differ between methods")
            eligibility = group_eligibility(
                len(esm_rows), len({row.component_id for row in esm_rows})
            )
            difference: float | None = None
            lower: float | None = None
            upper: float | None = None
            if esm_rows:
                comparison = paired_metric_difference(
                    esm_rows,
                    nearest_rows,
                    metric="accuracy",
                )
                difference = comparison.point_difference
                lower = comparison.ci_lower
                upper = comparison.ci_upper
            rows.append(
                (
                    1,
                    "confirmatory",
                    split_order,
                    split,
                    stratum_order,
                    stratum_id,
                    len(measures) + 1,
                    "accuracy_difference_esm2_150m_minus_nearest_homolog",
                    METHODS.index("esm2-150m"),
                    "esm2-150m-minus-nearest-homolog",
                    eligibility.sequence_count_display,
                    eligibility.public_sequence_count,
                    eligibility.component_count_display,
                    eligibility.public_component_count,
                    difference,
                    lower,
                    upper,
                    eligibility.reporting_status,
                )
            )
    return csv_bytes(CSV_SCHEMAS["nearest_homolog_summary.csv"], rows)


def _agreement_table(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    rows: list[tuple[object, ...]] = []
    for split_order, split in enumerate(SPLITS):
        for comparison_order, (method_a, method_b) in enumerate(AGREEMENT_PAIRS):
            result = prediction_agreement(cells[(split, method_a)], cells[(split, method_b)])
            eligibility = result.eligibility
            fractions_allowed = eligibility.reporting_status != "privacy_suppressed"
            rows.append(
                (
                    1,
                    "confirmatory",
                    split_order,
                    split,
                    comparison_order,
                    method_a,
                    method_b,
                    result.both_correct if fractions_allowed else None,
                    result.both_wrong if fractions_allowed else None,
                    result.method_a_only_correct if fractions_allowed else None,
                    result.method_b_only_correct if fractions_allowed else None,
                    result.both_correct / result.total if fractions_allowed else None,
                    result.both_wrong / result.total if fractions_allowed else None,
                    result.method_a_only_correct / result.total if fractions_allowed else None,
                    result.method_b_only_correct / result.total if fractions_allowed else None,
                    eligibility.sequence_count_display,
                    eligibility.public_sequence_count,
                    eligibility.component_count_display,
                    eligibility.public_component_count,
                    eligibility.reporting_status,
                )
            )
    return csv_bytes(CSV_SCHEMAS["prediction_agreement.csv"], rows)


def _influence_table(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    rows: list[tuple[object, ...]] = []
    for split_order, split in enumerate(SPLITS):
        for method_order, method in enumerate(METHODS):
            for metric_order, metric in enumerate(METRICS):
                for removal_order, item in enumerate(
                    component_influence(cells[(split, method)], metric=metric)
                ):
                    eligibility = item.eligibility
                    counts_allowed = eligibility.reporting_status != "privacy_suppressed"
                    rows.append(
                        (
                            1,
                            "confirmatory",
                            split_order,
                            split,
                            method_order,
                            method,
                            metric_order,
                            metric,
                            removal_order,
                            item.removal_count,
                            item.removed_sequence_count if counts_allowed else None,
                            eligibility.sequence_count_display,
                            eligibility.public_sequence_count,
                            eligibility.component_count_display,
                            eligibility.public_component_count,
                            item.estimate,
                            item.ci_lower,
                            item.ci_upper,
                            eligibility.reporting_status,
                        )
                    )
    return csv_bytes(CSV_SCHEMAS["component_influence.csv"], rows)


def _robustness_table(
    cells: Mapping[tuple[str, str], tuple[AnalysisRow, ...]],
) -> bytes:
    status_order = {
        "privacy_suppressed": 0,
        "insufficient_sequences": 1,
        "insufficient_components_for_ci": 2,
        "reportable": 3,
    }

    def least_status(values: Sequence[str]) -> str:
        return min(values, key=status_order.__getitem__)

    rows: list[tuple[object, ...]] = []
    order = 0
    for method in METHODS:
        differences: dict[MetricName, float] = {}
        statuses: list[str] = []
        gap_results: dict[MetricName, IndependentSplitGap] = {}
        for metric in METRICS:
            gap_result = independent_split_gap(
                cells[("random", method)],
                cells[("cluster30", method)],
                metric=metric,
            )
            gap_results[metric] = gap_result
            statuses.extend(
                (
                    gap_result.random_eligibility.reporting_status,
                    gap_result.comparison_eligibility.reporting_status,
                )
            )
            if gap_result.point_difference is not None:
                differences[metric] = gap_result.point_difference
        accuracy: object
        balanced: object
        macro: object
        agree: object
        direction: object
        if len(differences) == 3:
            signs = sign_concordance(
                accuracy=differences["accuracy"],
                balanced_accuracy=differences["balanced_accuracy"],
                macro_f1=differences["macro_f1"],
            )
            accuracy = signs.accuracy
            balanced = signs.balanced_accuracy
            macro = signs.macro_f1
            agree = signs.signs_agree
            direction = signs.direction
        else:
            accuracy = None
            balanced = None
            macro = None
            agree = None
            direction = None
        status = least_status(statuses)
        rows.append(
            (
                1,
                "confirmatory",
                order,
                "class_balance_generalization",
                SPLITS.index("cluster30"),
                "cluster30",
                method,
                None,
                None,
                None,
                accuracy,
                balanced,
                macro,
                agree,
                direction,
                2026,
                None,
                None,
                None,
                None,
                status,
            )
        )
        order += 1
        for metric_order, metric in enumerate(METRICS):
            primary = gap_results[metric]
            shifts: tuple[object, object, object] = (None, None, None)
            if primary.ci_lower is not None and primary.ci_upper is not None:
                alternatives = tuple(
                    independent_split_gap(
                        cells[("random", method)],
                        cells[("cluster30", method)],
                        metric=metric,
                        seed=seed,
                    )
                    for seed in (3407, 42)
                )
                if all(
                    item.ci_lower is not None and item.ci_upper is not None for item in alternatives
                ):
                    diagnostic = seed_diagnostic(
                        primary=(primary.ci_lower, primary.ci_upper),
                        alternatives=tuple(
                            (seed, item.ci_lower, item.ci_upper)
                            for seed, item in zip((3407, 42), alternatives, strict=True)
                            if item.ci_lower is not None and item.ci_upper is not None
                        ),
                    )
                    shifts = (
                        diagnostic.maximum_lower_shift,
                        diagnostic.maximum_upper_shift,
                        diagnostic.maximum_width_shift,
                    )
            rows.append(
                (
                    1,
                    "confirmatory",
                    order,
                    "bootstrap_seed_generalization",
                    SPLITS.index("cluster30"),
                    "cluster30",
                    method,
                    None,
                    metric_order,
                    metric,
                    None,
                    None,
                    None,
                    None,
                    None,
                    2026,
                    "3407;42",
                    *shifts,
                    least_status(
                        (
                            primary.random_eligibility.reporting_status,
                            primary.comparison_eligibility.reporting_status,
                        )
                    ),
                )
            )
            order += 1
    for split_order, split in enumerate(SPLITS):
        for method_a, method_b in RQ5_COMPARISONS:
            comparison_differences: dict[MetricName, float] = {}
            comparison_results: dict[MetricName, PairedMetricDifference] = {}
            for metric in METRICS:
                comparison_result = paired_metric_difference(
                    cells[(split, method_a)],
                    cells[(split, method_b)],
                    metric=metric,
                )
                comparison_results[metric] = comparison_result
                if comparison_result.point_difference is not None:
                    comparison_differences[metric] = comparison_result.point_difference
            if len(comparison_differences) == 3:
                signs = sign_concordance(
                    accuracy=comparison_differences["accuracy"],
                    balanced_accuracy=comparison_differences["balanced_accuracy"],
                    macro_f1=comparison_differences["macro_f1"],
                )
                values: tuple[object, ...] = (
                    signs.accuracy,
                    signs.balanced_accuracy,
                    signs.macro_f1,
                    signs.signs_agree,
                    signs.direction,
                )
            else:
                values = (None, None, None, None, None)
            rows.append(
                (
                    1,
                    "confirmatory",
                    order,
                    "class_balance_method_difference",
                    split_order,
                    split,
                    method_a,
                    method_b,
                    None,
                    None,
                    *values,
                    2026,
                    None,
                    None,
                    None,
                    None,
                    least_status(
                        tuple(
                            item.eligibility.reporting_status
                            for item in comparison_results.values()
                        )
                    ),
                )
            )
            order += 1
            for metric_order, metric in enumerate(METRICS):
                paired_primary = comparison_results[metric]
                shifts = (None, None, None)
                if paired_primary.ci_lower is not None and paired_primary.ci_upper is not None:
                    paired_alternatives = tuple(
                        paired_metric_difference(
                            cells[(split, method_a)],
                            cells[(split, method_b)],
                            metric=metric,
                            seed=seed,
                        )
                        for seed in (3407, 42)
                    )
                    if all(
                        item.ci_lower is not None and item.ci_upper is not None
                        for item in paired_alternatives
                    ):
                        diagnostic = seed_diagnostic(
                            primary=(paired_primary.ci_lower, paired_primary.ci_upper),
                            alternatives=tuple(
                                (seed, item.ci_lower, item.ci_upper)
                                for seed, item in zip((3407, 42), paired_alternatives, strict=True)
                                if item.ci_lower is not None and item.ci_upper is not None
                            ),
                        )
                        shifts = (
                            diagnostic.maximum_lower_shift,
                            diagnostic.maximum_upper_shift,
                            diagnostic.maximum_width_shift,
                        )
                rows.append(
                    (
                        1,
                        "confirmatory",
                        order,
                        "bootstrap_seed_method_difference",
                        split_order,
                        split,
                        method_a,
                        method_b,
                        metric_order,
                        metric,
                        None,
                        None,
                        None,
                        None,
                        None,
                        2026,
                        "3407;42",
                        *shifts,
                        paired_primary.eligibility.reporting_status,
                    )
                )
                order += 1
    return csv_bytes(CSV_SCHEMAS["robustness_summary.csv"], rows)


def build_analysis_outputs(
    rows: Sequence[AnalysisRow],
    *,
    manifest_context: Mapping[str, object],
    strict_row_count: bool = True,
) -> dict[str, bytes]:
    """Build all ten deterministic aggregate tables and one content manifest."""

    cells = _cell_rows(rows, strict_row_count=strict_row_count)
    outputs = {
        "split_performance_summary.csv": _split_performance(cells),
        "identity_bin_summary.csv": _stratified_table(
            cells,
            dimension="identity",
            filename="identity_bin_summary.csv",
        ),
        "length_bin_summary.csv": _stratified_table(
            cells,
            dimension="length",
            filename="length_bin_summary.csv",
        ),
        "component_size_summary.csv": _stratified_table(
            cells,
            dimension="component_size",
            filename="component_size_summary.csv",
        ),
        "class_error_summary.csv": _class_errors(cells),
        "nearest_homolog_summary.csv": _nearest_table(cells),
        "model_comparisons.csv": _comparison_table(cells),
        "prediction_agreement.csv": _agreement_table(cells),
        "component_influence.csv": _influence_table(cells),
        "robustness_summary.csv": _robustness_table(cells),
    }
    figure_sources = {
        "figures/generalization_gap.pdf": "split_performance_summary.csv",
        "figures/macro_f1_by_split.pdf": "split_performance_summary.csv",
        "figures/nearest_homolog_analysis.pdf": "nearest_homolog_summary.csv",
        "figures/per_class_gap.pdf": "class_error_summary.csv",
        "figures/performance_by_identity.pdf": "identity_bin_summary.csv",
        "figures/performance_by_length.pdf": "length_bin_summary.csv",
    }
    manifest = {
        "analysis_class": "confirmatory",
        "bootstrap": {
            "confidence_level": 0.95,
            "diagnostic_seeds": [2026, 3407, 42],
            "interval_method": "percentile",
            "iterations": 2000,
            "primary_seed": 2026,
            "unit": "cluster30_discovery_component",
        },
        "component_influence_removals": [0, 1, 3, 5],
        "component_size_bins": [item.id for item in COMPONENT_SIZE_BINS],
        "context": dict(manifest_context),
        "figure_sources": {
            figure: {
                "source": source,
                "source_sha256": sha256_bytes(outputs[source]),
            }
            for figure, source in sorted(figure_sources.items())
        },
        "git_dirty": False,
        "identity_bins": [item.id for item in IDENTITY_BINS],
        "label_order": LABEL_ORDER,
        "length_bins": [item.id for item in LENGTH_BINS],
        "methods": METHODS,
        "method_comparisons": {
            "rq5": [list(pair) for pair in RQ5_COMPARISONS],
            "rq6": ["esm2-150m", "nearest-homolog"],
        },
        "output_sha256": {name: sha256_bytes(content) for name, content in sorted(outputs.items())},
        "privacy_thresholds": {
            "minimum_components_for_ci": 10,
            "minimum_sequences_for_metric": 20,
            "suppress_below_components": 3,
            "suppress_below_sequences": 5,
        },
        "privacy_scan": {
            "required_before_release": True,
            "status": "pending_review_bundle",
        },
        "public_artifacts": PUBLIC_ARTIFACTS,
        "row_count": len(tuple(rows)),
        "schema_version": 1,
        "software_version": __version__,
        "splits": SPLITS,
    }
    outputs["analysis_manifest.json"] = json_bytes(manifest)
    return outputs


def run_post_test_analysis(
    config_path: Path,
    attestation_path: Path,
    session: AnalysisSession,
    output_dir: Path,
) -> AnalysisRunResult:
    """Verify authority, consume one session, and write aggregates without stdout metrics."""

    from protein_split_audit.analysis.authorization import verify_analysis_authorization
    from protein_split_audit.analysis.inputs import load_frozen_analysis_rows
    from protein_split_audit.config import load_analysis_config
    from protein_split_audit.paths import find_project_root

    root = find_project_root(config_path)
    if root is None:
        raise RuntimeError("project root is unavailable")
    config = load_analysis_config(config_path)
    try:
        session_index = config.outputs.formal_sessions.index(session)
    except ValueError as error:
        raise ValueError("formal session differs from the frozen configuration") from error
    expected = (config.outputs.run_a_root, config.outputs.run_b_root)[session_index]
    if output_dir.resolve() != expected:
        raise ValueError("formal output directory differs from the frozen configuration")
    authorization = verify_analysis_authorization(config_path, attestation_path, root)
    ledger = expected.parent / "v0.6.0-access-ledger" / f"{session}.json"
    if ledger.exists() or expected.exists():
        raise FileExistsError("formal analysis session has already been consumed")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger_content = json_bytes(
        {
            "consumed_at_utc": datetime.now(UTC).isoformat(),
            "execution_commit": authorization.execution_commit,
            "schema_version": 1,
            "session": session,
        }
    )
    publish_bundle({ledger: ledger_content})
    try:
        rows = load_frozen_analysis_rows(config, authorization)
        outputs = build_analysis_outputs(
            rows,
            manifest_context={
                "approval_reference": authorization.approval_reference,
                "attestation_sha256": authorization.attestation_sha256,
                "config_sha256": authorization.config_sha256,
                "execution_commit": authorization.execution_commit,
                "frozen_input_hashes": dict(authorization.frozen_hashes),
                "lock_sha256": authorization.lock_sha256,
                "protocol_sha256": authorization.protocol_sha256,
            },
        )
        result = write_deterministic_bundle(expected, outputs)
        provenance = json_bytes(
            {
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "schema_version": 1,
                "session": session,
            }
        )
        publish_bundle({expected / "run_provenance.json": provenance})
        (expected / ".psaudit-publication.lock").unlink(missing_ok=True)
    except BaseException as error:
        incident = ledger.parent / f"{session}.incident.json"
        if not incident.exists():
            publish_bundle(
                {
                    incident: json_bytes(
                        {
                            "error_type": type(error).__name__,
                            "recorded_at_utc": datetime.now(UTC).isoformat(),
                            "schema_version": 1,
                            "session": session,
                        }
                    )
                }
            )
        raise
    return AnalysisRunResult(session, expected, result.file_sha256)


def write_review_aggregate(
    run_a: Path,
    replay_report: Path,
    attestation: Path,
    output_dir: Path,
) -> AnalysisAggregateResult:
    """Stage only deterministic aggregates after verifying the persisted replay proof."""

    import json as json_module

    from protein_split_audit.analysis.replay import deterministic_inventory_sha256
    from protein_split_audit.provenance import sha256_file

    report = json_module.loads(replay_report.read_text(encoding="utf-8"))
    if (
        report.get("aggregate_authorized") is not True
        or report.get("deterministic_mismatch_count") != 0
        or report.get("run_a_inventory_sha256") != deterministic_inventory_sha256(run_a)
    ):
        raise RuntimeError("analysis aggregate is not authorized by an exact replay")
    manifest_path = run_a / "analysis_manifest.json"
    manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
    context = manifest.get("context")
    if not isinstance(context, dict) or context.get("attestation_sha256") != sha256_file(
        attestation
    ):
        raise RuntimeError("analysis aggregate attestation identity is invalid")
    outputs: dict[str, bytes] = {}
    for filename in CSV_SCHEMAS:
        outputs[filename] = (run_a / filename).read_bytes()
    outputs["analysis_manifest.json"] = manifest_path.read_bytes()
    outputs["replay_report.json"] = replay_report.read_bytes()
    outputs["README.md"] = (
        b"# ProteinSplitAudit v0.6.0 aggregate\n\n"
        b"Confirmatory pilot summaries from the frozen v0.5.0 predictions. "
        b"These aggregate results are not a general benchmark and make no significance claim.\n"
    )
    result = write_deterministic_bundle(output_dir, outputs)
    return AnalysisAggregateResult(result.root, result.file_sha256)


__all__ = [
    "CSV_SCHEMAS",
    "SHARED_METRIC_COLUMNS",
    "AnalysisAggregateResult",
    "AnalysisRunResult",
    "DeterministicBundleResult",
    "build_analysis_outputs",
    "csv_bytes",
    "json_bytes",
    "run_post_test_analysis",
    "write_deterministic_bundle",
    "write_review_aggregate",
]
