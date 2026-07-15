# SPDX-License-Identifier: Apache-2.0

"""Pure deterministic eligibility, ranking, and cohort-member selection."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from protein_split_audit.cohort.schemas import (
    CandidatePool,
    CandidateRecord,
    CohortFeasibilityConfig,
    CohortSelectionConfig,
)
from protein_split_audit.similarity.connected_components import ComponentPartition
from protein_split_audit.splits.allocator import (
    AllocatorConfig as ExactAllocatorConfig,
)
from protein_split_audit.splits.allocator import (
    AllocatorWeights,
    GroupAllocation,
    SimilarityGroup,
    allocate_components,
)

_EC_LEVEL_2_PATTERN = re.compile(r"^\d+\.\d+$")


class CohortSelectionError(ValueError):
    """Raised when fixed cohort-selection inputs or rules cannot be satisfied."""


@dataclass(frozen=True, slots=True)
class CohortClassProfile:
    """Aggregate eligibility facts for one EC-level-2 class."""

    ec_level_2: str
    candidate_count: int
    discovery_component_count: int
    capped_count: int
    eligible: bool
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CohortEligibilityProfile:
    """Aggregate eligibility facts derived from an exact candidate/discovery join."""

    classes: tuple[CohortClassProfile, ...]


@dataclass(frozen=True, slots=True)
class ClassDecision:
    """One row in the complete deterministic eligible-class ranking."""

    ec_level_2: str
    candidate_count: int
    discovery_component_count: int
    capped_count: int
    eligible_rank: int
    selected: bool


@dataclass(frozen=True, slots=True)
class SelectedCohortMember:
    """One provisionally selected candidate and its discovery30 component."""

    candidate: CandidateRecord
    discovery_component_id_cluster30: str


@dataclass(frozen=True, slots=True)
class CohortSourceHashes:
    """Candidate input identities carried into provisional selection."""

    dataset_sha256: str
    build_manifest_sha256: str
    fasta_sha256: str


@dataclass(frozen=True, slots=True)
class SelectedCohort:
    """A deterministic provisional selection that has not crossed the freeze gate."""

    members: tuple[SelectedCohortMember, ...]
    selected_labels: tuple[str, ...]
    eligible_ranking: tuple[ClassDecision, ...]
    exclusion_reason_counts: tuple[tuple[str, int], ...]
    feasibility: GroupAllocation
    source_hashes: CohortSourceHashes


def _ec_key(label: str) -> tuple[int, int, str]:
    if _EC_LEVEL_2_PATTERN.fullmatch(label) is None:
        raise CohortSelectionError(f"invalid EC-level-2 label: {label!r}")
    first, second = label.split(".")
    return int(first), int(second), label


def _sha256_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _candidate_component_ids(
    pool: CandidatePool,
    discovery: ComponentPartition,
) -> dict[str, str]:
    if discovery.threshold != Decimal("0.30"):
        raise CohortSelectionError("discovery partition threshold must be exactly 0.30")

    candidate_identities: set[tuple[str, str]] = set()
    accessions: set[str] = set()
    hashes: set[str] = set()
    for record in pool.records:
        _ec_key(record.ec_level_2)
        identity = (record.accession, record.sequence_sha256)
        if (
            identity in candidate_identities
            or record.accession in accessions
            or record.sequence_sha256 in hashes
        ):
            raise CohortSelectionError("candidate pool contains a duplicate identity")
        candidate_identities.add(identity)
        accessions.add(record.accession)
        hashes.add(record.sequence_sha256)

    discovery_identities = {
        (membership.node.accession, membership.node.sequence_sha256)
        for membership in discovery.rows
    }
    if candidate_identities != discovery_identities:
        raise CohortSelectionError(
            "candidate pool and discovery partition identities do not match exactly"
        )
    return {membership.node.accession: membership.component_id for membership in discovery.rows}


def profile_cohort_eligibility(
    pool: CandidatePool,
    discovery: ComponentPartition,
    rules: CohortSelectionConfig,
) -> CohortEligibilityProfile:
    """Join verified inputs and compute both fixed class-eligibility gates."""

    component_by_accession = _candidate_component_ids(pool, discovery)
    candidate_counts = Counter(record.ec_level_2 for record in pool.records)
    components_by_label: dict[str, set[str]] = defaultdict(set)
    for record in pool.records:
        components_by_label[record.ec_level_2].add(component_by_accession[record.accession])

    classes: list[CohortClassProfile] = []
    for label in sorted(candidate_counts, key=_ec_key):
        candidate_count = candidate_counts[label]
        component_count = len(components_by_label[label])
        reasons: list[str] = []
        if candidate_count < rules.min_sequences_per_class:
            reasons.append("insufficient_candidates")
        if component_count < rules.min_groups_per_class_at_cluster30:
            reasons.append("insufficient_cluster30_components")
        classes.append(
            CohortClassProfile(
                ec_level_2=label,
                candidate_count=candidate_count,
                discovery_component_count=component_count,
                capped_count=min(candidate_count, rules.max_sequences_per_class),
                eligible=not reasons,
                exclusion_reasons=tuple(reasons),
            )
        )
    return CohortEligibilityProfile(classes=tuple(classes))


def rank_eligible_classes(
    profile: CohortEligibilityProfile,
    rules: CohortSelectionConfig,
) -> tuple[ClassDecision, ...]:
    """Rank eligible classes and select exactly five without fallback."""

    eligible = sorted(
        (row for row in profile.classes if row.eligible),
        key=lambda row: (
            -row.capped_count,
            -row.discovery_component_count,
            _ec_key(row.ec_level_2),
        ),
    )
    if len(eligible) < rules.number_of_classes:
        raise CohortSelectionError(
            "pilot cohort requires exactly "
            f"{rules.number_of_classes} eligible EC-level-2 classes; found {len(eligible)} under "
            f"{rules.selection_rule_version} (minimum candidates="
            f"{rules.min_sequences_per_class}, minimum cluster30 components="
            f"{rules.min_groups_per_class_at_cluster30}); no fallback was applied"
        )
    return tuple(
        ClassDecision(
            ec_level_2=row.ec_level_2,
            candidate_count=row.candidate_count,
            discovery_component_count=row.discovery_component_count,
            capped_count=row.capped_count,
            eligible_rank=index,
            selected=index <= rules.number_of_classes,
        )
        for index, row in enumerate(eligible, start=1)
    )


def _select_label_members(
    records: Sequence[CandidateRecord],
    component_by_accession: dict[str, str],
    rules: CohortSelectionConfig,
) -> tuple[SelectedCohortMember, ...]:
    label = records[0].ec_level_2
    cap = rules.max_sequences_per_class
    members = tuple(
        SelectedCohortMember(
            candidate=record,
            discovery_component_id_cluster30=component_by_accession[record.accession],
        )
        for record in records
    )
    if len(members) <= cap:
        return members

    grouped: dict[str, list[SelectedCohortMember]] = defaultdict(list)
    for member in members:
        grouped[member.discovery_component_id_cluster30].append(member)

    def member_key(member: SelectedCohortMember) -> tuple[str, str, str]:
        candidate = member.candidate
        return (
            _sha256_key(f"{rules.seed}\n{candidate.accession}\n{candidate.sequence_sha256}"),
            candidate.accession,
            candidate.sequence_sha256,
        )

    ordered_components = sorted(
        grouped,
        key=lambda component_id: (
            _sha256_key(f"{rules.seed}\n{label}\n{component_id}"),
            component_id,
        ),
    )
    for component_id in ordered_components:
        grouped[component_id].sort(key=member_key)

    selected: list[SelectedCohortMember] = []
    selected_identities: set[tuple[str, str]] = set()
    for component_id in ordered_components:
        if len(selected) == cap:
            break
        member = grouped[component_id][0]
        selected.append(member)
        selected_identities.add((member.candidate.accession, member.candidate.sequence_sha256))

    remaining = sorted(
        (
            member
            for member in members
            if (member.candidate.accession, member.candidate.sequence_sha256)
            not in selected_identities
        ),
        key=member_key,
    )
    selected.extend(remaining[: cap - len(selected)])
    return tuple(selected)


def select_cohort_members(
    pool: CandidatePool,
    discovery: ComponentPartition,
    decisions: Sequence[ClassDecision],
    rules: CohortSelectionConfig,
) -> tuple[SelectedCohortMember, ...]:
    """Apply the fixed component-aware cap and return canonical provisional rows."""

    component_by_accession = _candidate_component_ids(pool, discovery)
    selected_labels = tuple(decision.ec_level_2 for decision in decisions if decision.selected)
    if len(selected_labels) != rules.number_of_classes or len(set(selected_labels)) != len(
        selected_labels
    ):
        raise CohortSelectionError("class decisions do not select exactly five unique classes")
    known_labels = {record.ec_level_2 for record in pool.records}
    if not set(selected_labels).issubset(known_labels):
        raise CohortSelectionError("class decisions contain a label outside the candidate pool")

    records_by_label: dict[str, list[CandidateRecord]] = defaultdict(list)
    for record in pool.records:
        if record.ec_level_2 in selected_labels:
            records_by_label[record.ec_level_2].append(record)

    selected_members: list[SelectedCohortMember] = []
    for label in selected_labels:
        selected_members.extend(
            _select_label_members(records_by_label[label], component_by_accession, rules)
        )
    selected_members.sort(
        key=lambda member: (
            _ec_key(member.candidate.ec_level_2),
            member.candidate.accession,
            member.candidate.sequence_sha256,
        )
    )
    return tuple(selected_members)


def _exact_allocator_config(
    selected_labels: tuple[str, ...],
    rules: CohortSelectionConfig,
    feasibility: CohortFeasibilityConfig,
) -> ExactAllocatorConfig:
    ratios = (
        Fraction(Decimal(str(feasibility.ratios.train))),
        Fraction(Decimal(str(feasibility.ratios.validation))),
        Fraction(Decimal(str(feasibility.ratios.test))),
    )
    weights = AllocatorWeights(
        size=Fraction(Decimal(str(feasibility.allocator.size_weight))),
        class_balance=Fraction(Decimal(str(feasibility.allocator.class_balance_weight))),
        group_count=Fraction(Decimal(str(feasibility.allocator.group_count_weight))),
        missing_class=Fraction(Decimal(str(feasibility.allocator.missing_class_weight))),
    )
    return ExactAllocatorConfig(
        required_labels=selected_labels,
        seed=rules.seed,
        ratios=ratios,
        ratio_tolerance=Fraction(Decimal(str(feasibility.ratio_tolerance))),
        version=feasibility.allocator.version,
        weights=weights,
    )


def _similarity_groups(
    members: Sequence[SelectedCohortMember],
) -> tuple[SimilarityGroup, ...]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for member in members:
        counts[member.discovery_component_id_cluster30][member.candidate.ec_level_2] += 1
    return tuple(
        SimilarityGroup(
            component_id=component_id,
            class_counts=tuple(class_counts.items()),
        )
        for component_id, class_counts in sorted(counts.items())
    )


def select_cohort(
    pool: CandidatePool,
    discovery: ComponentPartition,
    rules: CohortSelectionConfig,
    feasibility: CohortFeasibilityConfig,
) -> SelectedCohort:
    """Select a provisional cohort and require fixed grouped-split feasibility."""

    profile = profile_cohort_eligibility(pool, discovery, rules)
    decisions = rank_eligible_classes(profile, rules)
    members = select_cohort_members(pool, discovery, decisions, rules)
    selected_labels = tuple(decision.ec_level_2 for decision in decisions if decision.selected)
    allocation = allocate_components(
        _similarity_groups(members),
        _exact_allocator_config(selected_labels, rules, feasibility),
    )
    if not allocation.feasible:
        codes = ", ".join(allocation.diagnostic.failure_codes)
        raise CohortSelectionError(
            "pilot cohort fails deterministic cluster30 allocation feasibility"
            f" ({codes}); no component was split and no fallback was applied"
        )
    exclusion_counts = Counter(
        reason for row in profile.classes for reason in row.exclusion_reasons
    )
    return SelectedCohort(
        members=members,
        selected_labels=selected_labels,
        eligible_ranking=decisions,
        exclusion_reason_counts=tuple(sorted(exclusion_counts.items())),
        feasibility=allocation,
        source_hashes=CohortSourceHashes(
            dataset_sha256=pool.dataset_sha256,
            build_manifest_sha256=pool.build_manifest_sha256,
            fasta_sha256=pool.fasta_sha256,
        ),
    )


def validate_cohort_selection(
    cohort: SelectedCohort,
    pool: CandidatePool,
    discovery: ComponentPartition,
    rules: CohortSelectionConfig,
    feasibility: CohortFeasibilityConfig,
) -> None:
    """Recompute every provisional selection decision and require exact equality."""

    expected = select_cohort(pool, discovery, rules, feasibility)
    if cohort != expected:
        raise CohortSelectionError("cohort selection disagrees with deterministic recomputation")


__all__ = [
    "ClassDecision",
    "CohortClassProfile",
    "CohortEligibilityProfile",
    "CohortSelectionError",
    "CohortSourceHashes",
    "SelectedCohort",
    "SelectedCohortMember",
    "profile_cohort_eligibility",
    "rank_eligible_classes",
    "select_cohort",
    "select_cohort_members",
    "validate_cohort_selection",
]
