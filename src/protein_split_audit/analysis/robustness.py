# SPDX-License-Identifier: Apache-2.0

"""Pre-specified robustness and correctness-agreement diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from protein_split_audit.analysis.binning import BinAssignment
from protein_split_audit.analysis.inputs import AnalysisRow
from protein_split_audit.analysis.privacy import GroupEligibility, group_eligibility
from protein_split_audit.analysis.schemas import MethodName, MetricName
from protein_split_audit.analysis.stratified_metrics import aggregate_metric

AGREEMENT_PAIRS: tuple[tuple[MethodName, MethodName], ...] = (
    ("aac-logistic", "esm2-150m"),
    ("kmer3-logistic", "esm2-150m"),
    ("nearest-homolog", "esm2-150m"),
)


@dataclass(frozen=True, slots=True)
class ComponentInfluenceResult:
    """Metric after cumulative removal of the largest Test components."""

    removal_count: int
    removed_sequence_count: int
    remaining_sequence_count: int
    remaining_component_count: int
    estimate: float | None
    ci_lower: float | None
    ci_upper: float | None
    bootstrap_seed: int | None
    eligibility: GroupEligibility


@dataclass(frozen=True, slots=True)
class SignConcordance:
    """Direction agreement across the three frozen metric families."""

    accuracy: float
    balanced_accuracy: float
    macro_f1: float
    signs_agree: bool
    direction: str


@dataclass(frozen=True, slots=True)
class SeedDiagnostic:
    """Descriptive interval sensitivity with no invented pass/fail threshold."""

    primary_seed: int
    diagnostic_seeds: tuple[int, ...]
    maximum_lower_shift: float
    maximum_upper_shift: float
    maximum_width_shift: float
    pass_fail: None = None


@dataclass(frozen=True, slots=True)
class PredictionAgreement:
    """Four-cell correctness relation for one pre-registered method pair."""

    method_a: MethodName
    method_b: MethodName
    both_correct: int
    both_wrong: int
    method_a_only_correct: int
    method_b_only_correct: int
    total: int
    component_count: int
    eligibility: GroupEligibility


def rank_components(rows: Sequence[AnalysisRow]) -> tuple[str, ...]:
    """Rank Test-represented components by count descending then private ID."""

    counts = Counter(row.component_id for row in rows)
    if not counts or any(not component for component in counts):
        raise ValueError("component ranking requires nonempty component identities")
    return tuple(sorted(counts, key=lambda component: (-counts[component], component)))


def component_influence(
    rows: Sequence[AnalysisRow],
    *,
    metric: MetricName,
) -> tuple[ComponentInfluenceResult, ...]:
    """Recompute existing prediction metrics after fixed cumulative removals."""

    records = tuple(rows)
    if not records:
        raise ValueError("component influence requires prediction rows")
    if len({row.method for row in records}) != 1 or len({row.split_name for row in records}) != 1:
        raise ValueError("component influence requires one method and split")
    ranking = rank_components(records)
    output: list[ComponentInfluenceResult] = []
    for removal_count in (0, 1, 3, 5):
        removed = set(ranking[:removal_count])
        retained = tuple(row for row in records if row.component_id not in removed)
        eligibility = group_eligibility(len(retained), len({row.component_id for row in retained}))
        aggregate = aggregate_metric(
            retained,
            dimension="component_influence",
            stratum=BinAssignment(
                removal_count,
                f"remove_{removal_count}",
                f"Remove {removal_count}",
            ),
            metric=metric,
        )
        output.append(
            ComponentInfluenceResult(
                removal_count=removal_count,
                removed_sequence_count=len(records) - len(retained),
                remaining_sequence_count=len(retained),
                remaining_component_count=len({row.component_id for row in retained}),
                estimate=aggregate.estimate,
                ci_lower=aggregate.ci_lower,
                ci_upper=aggregate.ci_upper,
                bootstrap_seed=aggregate.bootstrap_seed,
                eligibility=eligibility,
            )
        )
    return tuple(output)


def _sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def sign_concordance(
    *,
    accuracy: float,
    balanced_accuracy: float,
    macro_f1: float,
) -> SignConcordance:
    """Describe whether unweighted and class-balanced directions agree."""

    values = (accuracy, balanced_accuracy, macro_f1)
    signs = tuple(_sign(value) for value in values)
    agree = len(set(signs)) == 1
    direction = {1: "positive", -1: "negative", 0: "zero"}.get(signs[0], "mixed")
    if not agree:
        direction = "mixed"
    return SignConcordance(accuracy, balanced_accuracy, macro_f1, agree, direction)


def seed_diagnostic(
    *,
    primary: tuple[float, float],
    alternatives: Sequence[tuple[int, float, float]],
) -> SeedDiagnostic:
    """Summarize endpoint and width shifts for seeds 3407 and 42."""

    observed = tuple(alternatives)
    if tuple(item[0] for item in observed) != (3407, 42):
        raise ValueError("diagnostic seeds must be exactly 3407 then 42")
    primary_lower, primary_upper = primary
    primary_width = primary_upper - primary_lower
    lower_shift = max(abs(lower - primary_lower) for _, lower, _ in observed)
    upper_shift = max(abs(upper - primary_upper) for _, _, upper in observed)
    width_shift = max(abs((upper - lower) - primary_width) for _, lower, upper in observed)
    return SeedDiagnostic(
        primary_seed=2026,
        diagnostic_seeds=(3407, 42),
        maximum_lower_shift=round(lower_shift, 15),
        maximum_upper_shift=round(upper_shift, 15),
        maximum_width_shift=round(width_shift, 15),
    )


def _agreement_inventory(rows: tuple[AnalysisRow, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            row.accession,
            row.sequence_sha256,
            row.true_label,
            row.component_id,
            row.nearest_train_identity,
            row.no_hit,
        )
        for row in rows
    )


def prediction_agreement(
    rows_a: Sequence[AnalysisRow],
    rows_b: Sequence[AnalysisRow],
) -> PredictionAgreement:
    """Count the four correctness cells after exact private row alignment."""

    first = tuple(rows_a)
    second = tuple(rows_b)
    if not first or not second:
        raise ValueError("prediction agreement requires two nonempty methods")
    methods_a = {row.method for row in first}
    methods_b = {row.method for row in second}
    if len(methods_a) != 1 or len(methods_b) != 1:
        raise ValueError("prediction agreement requires one method per side")
    method_a = next(iter(methods_a))
    method_b = next(iter(methods_b))
    if (method_a, method_b) not in AGREEMENT_PAIRS:
        raise ValueError("prediction agreement pair is not pre-registered")
    if _agreement_inventory(first) != _agreement_inventory(second):
        raise ValueError("agreement methods require an identical private row inventory")
    paired = tuple(zip(first, second, strict=True))
    both_correct = sum(left.correct and right.correct for left, right in paired)
    both_wrong = sum(not left.correct and not right.correct for left, right in paired)
    first_only = sum(left.correct and not right.correct for left, right in paired)
    second_only = sum(not left.correct and right.correct for left, right in paired)
    eligibility = group_eligibility(len(first), len({row.component_id for row in first}))
    return PredictionAgreement(
        method_a=method_a,
        method_b=method_b,
        both_correct=both_correct,
        both_wrong=both_wrong,
        method_a_only_correct=first_only,
        method_b_only_correct=second_only,
        total=len(first),
        component_count=len({row.component_id for row in first}),
        eligibility=eligibility,
    )


def signs_from_differences(differences: Mapping[MetricName, float]) -> SignConcordance:
    """Convenience adapter for a complete frozen metric mapping."""

    return sign_concordance(
        accuracy=differences["accuracy"],
        balanced_accuracy=differences["balanced_accuracy"],
        macro_f1=differences["macro_f1"],
    )


__all__ = [
    "AGREEMENT_PAIRS",
    "ComponentInfluenceResult",
    "PredictionAgreement",
    "SeedDiagnostic",
    "SignConcordance",
    "component_influence",
    "prediction_agreement",
    "rank_components",
    "seed_diagnostic",
    "sign_concordance",
    "signs_from_differences",
]
