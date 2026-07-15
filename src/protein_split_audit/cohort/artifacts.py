# SPDX-License-Identifier: Apache-2.0

"""Verified discovery inputs and deterministic cohort artifacts."""

from __future__ import annotations

import json
import platform
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Literal

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from protein_split_audit import __version__
from protein_split_audit.cohort.freeze import (
    DiscoveryFreezeLineage,
    FreezeEvidence,
    FreezeGateError,
    FreezeReview,
    validate_freeze_review,
)
from protein_split_audit.cohort.regeneration import (
    CandidateLineagePaths,
    load_candidate_lineage,
    load_regeneration_difference_report,
)
from protein_split_audit.cohort.schemas import CandidatePool
from protein_split_audit.cohort.select_cohort import (
    SelectedCohort,
    SelectedCohortMember,
    select_cohort,
)
from protein_split_audit.config import CohortConfigDocument, load_cohort_config_document
from protein_split_audit.data.build_candidates import PARQUET_WRITER_SETTINGS
from protein_split_audit.provenance import (
    GitMetadata,
    git_metadata,
    serialize_json_mapping,
    serialize_json_model,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.publication import PublicationError, publish_bundle
from protein_split_audit.similarity.connected_components import (
    ComponentError,
    ComponentMembership,
    ComponentPartition,
)
from protein_split_audit.similarity.discovery import COMPONENT_MANIFEST_SCHEMA
from protein_split_audit.similarity.parse_clusters import SequenceNode
from protein_split_audit.similarity.schemas import CandidateDiscoveryContentManifest

COHORT_MANIFEST_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence_sha256", pa.binary(32), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("sequence_length", pa.uint32(), nullable=False),
        pa.field("organism_id", pa.uint64(), nullable=False),
        pa.field("discovery_component_id_cluster30", pa.string(), nullable=False),
        pa.field("source_dataset_manifest", pa.string(), nullable=False),
        pa.field("source_dataset_manifest_sha256", pa.binary(32), nullable=False),
        pa.field("cohort_version", pa.string(), nullable=False),
        pa.field("selection_rule_version", pa.string(), nullable=False),
    ]
)


class CohortArtifactError(RuntimeError):
    """Raised when cohort inputs or serialized artifacts are inconsistent."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CohortParentLineage(_FrozenModel):
    """One exact parent manifest and its recorded generation state."""

    artifact_kind: Literal["download", "build", "discovery30", "difference", "review"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_git_commit: str | None
    generation_git_dirty: bool | None


class CohortArtifactDigest(_FrozenModel):
    """One generated artifact's logical location and deterministic hashes."""

    logical_path: str
    row_count: int = Field(ge=0)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CohortArtifactDigests(_FrozenModel):
    """Deterministic cohort row and sequence artifact identities."""

    cohort_manifest: CohortArtifactDigest
    fasta: CohortArtifactDigest


class CohortClassSummary(_FrozenModel):
    """Sequence-free aggregate selection facts for one eligible class."""

    ec_level_2: str
    eligible_rank: int = Field(ge=1)
    selected: bool
    candidate_count: int = Field(ge=1)
    discovery_component_count: int = Field(ge=1)
    selected_count: int = Field(ge=0)
    selected_component_count: int = Field(ge=0)


class CohortContentManifest(_FrozenModel):
    """Timestamp-free, sequence-free aggregate provisional cohort manifest."""

    manifest_schema_version: Literal[1] = 1
    cohort_artifact_schema_version: Literal[1] = 1
    cohort_version: Literal["pilot-v1-candidate", "pilot-v1"]
    run_mode: Literal["development", "freeze"]
    provisional: bool
    configuration_file: str
    source_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_rule_version: str
    selection_rules: dict[str, str | int]
    feasibility_rules: dict[str, str | int]
    selected_labels: tuple[str, ...]
    class_summaries: tuple[CohortClassSummary, ...]
    exclusion_reason_counts: dict[str, int]
    selection_evidence: tuple[Literal["candidate_count"], Literal["discovery_component_count"]]
    model_performance_used: Literal[False]
    parent_lineage: tuple[CohortParentLineage, ...]
    candidate_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_fasta_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_component_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_content_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: CohortArtifactDigests
    software_version: str
    generation_git_commit: str | None
    generation_git_dirty: bool | None
    python_version: str
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_eligible: bool
    ineligibility_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedDiscovery:
    """A verified discovery30 partition and its exact aggregate manifest identity."""

    partition: ComponentPartition
    content_manifest: CandidateDiscoveryContentManifest
    content_manifest_sha256: str
    component_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class SerializedCohortArtifacts:
    """Deterministic row/sequence artifact bytes and exact hashes."""

    parquet_bytes: bytes
    fasta_bytes: bytes
    parquet_sha256: str
    fasta_sha256: str
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class CohortBuildResult:
    """Published provisional cohort artifacts and aggregate result facts."""

    cohort_manifest: Path
    fasta: Path
    content_manifest: Path
    run_provenance: Path
    selected_count: int
    selected_labels: tuple[str, ...]
    content: CohortContentManifest


@dataclass(frozen=True, slots=True)
class CohortValidationReport:
    """Aggregate facts returned after deterministic cohort recomputation."""

    cohort_version: Literal["pilot-v1-candidate", "pilot-v1"]
    provisional: bool
    selected_count: int
    selected_labels: tuple[str, ...]
    cohort_manifest_sha256: str
    fasta_sha256: str
    content_manifest_sha256: str


def _as_decimal(value: object, label: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return Decimal(value)
    raise CohortArtifactError(f"component manifest {label} is not decimal")


def _as_int(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise CohortArtifactError(f"component manifest {label} is not an integer")


def _semantic_component_bytes(rows: list[dict[str, object]]) -> bytes:
    semantic_rows: list[list[object]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            str(item["similarity_component_id"]),
            str(item["accession"]),
        ),
    ):
        sequence_hash = row["sequence_sha256"]
        if not isinstance(sequence_hash, bytes) or len(sequence_hash) != 32:
            raise CohortArtifactError("component manifest contains an invalid sequence hash")
        semantic_rows.append(
            [
                row["accession"],
                sequence_hash.hex(),
                row["ec_level_2"],
                row["similarity_component_id"],
                row["similarity_component_representative"],
                row["component_size"],
                format(_as_decimal(row["identity_threshold"], "identity threshold"), ".2f"),
                format(_as_decimal(row["coverage_threshold"], "coverage threshold"), ".2f"),
                row["mmseqs_version"],
            ]
        )
    return b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        for row in semantic_rows
    )


def load_discovery_partition(
    component_manifest_path: Path,
    content_manifest_path: Path,
    *,
    pool: CandidatePool,
) -> ValidatedDiscovery:
    """Load the exact candidate-pool discovery30 component partition."""

    if not component_manifest_path.is_file() or not content_manifest_path.is_file():
        raise CohortArtifactError("discovery component or content manifest not found")
    try:
        content_bytes = content_manifest_path.read_bytes()
        content = CandidateDiscoveryContentManifest.model_validate_json(content_bytes)
    except (OSError, ValueError, ValidationError) as error:
        raise CohortArtifactError("invalid discovery content manifest") from error
    expected_hashes = (
        content.candidate_dataset_sha256,
        content.build_manifest_sha256,
        content.fasta_sha256,
    )
    actual_hashes = (pool.dataset_sha256, pool.build_manifest_sha256, pool.fasta_sha256)
    if expected_hashes != actual_hashes:
        raise CohortArtifactError("discovery candidate input hashes do not match candidate pool")
    expected_parent = (
        f"candidate-build:{pool.build_manifest_sha256}",
        pool.build_manifest_sha256,
        pool.build_manifest.git_commit,
        pool.build_manifest.git_dirty,
    )
    if len(content.parent_lineage) != 1:
        raise CohortArtifactError("discovery parent lineage must contain one candidate build")
    parent = content.parent_lineage[0]
    if (
        parent.artifact_id,
        parent.manifest_sha256,
        parent.generation_git_commit,
        parent.generation_git_dirty,
    ) != expected_parent:
        raise CohortArtifactError("discovery parent lineage does not match candidate build")
    component_sha256 = sha256_file(component_manifest_path)
    artifact = content.artifacts.component_manifest
    if component_sha256 != artifact.file_sha256:
        raise CohortArtifactError("discovery component manifest hash mismatch")
    try:
        parquet = pq.ParquetFile(component_manifest_path)
        if not parquet.schema_arrow.equals(COMPONENT_MANIFEST_SCHEMA, check_metadata=False):
            raise CohortArtifactError("discovery component manifest schema mismatch")
        table = parquet.read()
        rows: list[dict[str, object]] = [dict(row) for row in table.to_pylist()]
    except CohortArtifactError:
        raise
    except (OSError, ValueError, pa.ArrowException) as error:
        raise CohortArtifactError("unable to read discovery component manifest") from error
    if len(rows) != artifact.row_count or len(rows) != content.counts.sequence_count:
        raise CohortArtifactError("discovery component row count mismatch")
    if sha256_bytes(_semantic_component_bytes(rows)) != artifact.semantic_sha256:
        raise CohortArtifactError("discovery component semantic hash mismatch")

    candidate_by_accession = {record.accession: record for record in pool.records}
    memberships: list[ComponentMembership] = []
    try:
        for row in rows:
            accession = str(row["accession"])
            sequence_bytes = row["sequence_sha256"]
            if not isinstance(sequence_bytes, bytes):
                raise CohortArtifactError("component manifest sequence hash is not bytes")
            sequence_hash = sequence_bytes.hex()
            record = candidate_by_accession.get(accession)
            if (
                record is None
                or record.sequence_sha256 != sequence_hash
                or record.ec_level_2 != row["ec_level_2"]
            ):
                raise CohortArtifactError("component row identity disagrees with candidate pool")
            if _as_decimal(row["identity_threshold"], "identity threshold") != Decimal("0.30"):
                raise CohortArtifactError("discovery component threshold must be exactly 0.30")
            if _as_decimal(row["coverage_threshold"], "coverage threshold") != Decimal("0.80"):
                raise CohortArtifactError("discovery component coverage must be exactly 0.80")
            if row["mmseqs_version"] != content.command.mmseqs_version:
                raise CohortArtifactError("discovery MMseqs2 versions disagree")
            representative_accession = str(row["similarity_component_representative"])
            representative_record = candidate_by_accession.get(representative_accession)
            if representative_record is None:
                raise CohortArtifactError("component representative is outside candidate pool")
            memberships.append(
                ComponentMembership(
                    node=SequenceNode(
                        accession=accession,
                        sequence_sha256=sequence_hash,
                    ),
                    component_id=str(row["similarity_component_id"]),
                    representative=SequenceNode(
                        accession=representative_accession,
                        sequence_sha256=representative_record.sequence_sha256,
                    ),
                    component_size=_as_int(row["component_size"], "component size"),
                )
            )
        partition = ComponentPartition(
            threshold=Decimal("0.30"),
            rows=tuple(memberships),
        )
    except (ComponentError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, CohortArtifactError):
            raise
        raise CohortArtifactError("invalid discovery component membership") from error
    return ValidatedDiscovery(
        partition=partition,
        content_manifest=content,
        content_manifest_sha256=sha256_bytes(content_bytes),
        component_manifest_sha256=component_sha256,
    )


def _cohort_member_key(member: SelectedCohortMember) -> tuple[int, int, str, str, str]:
    first, second = member.candidate.ec_level_2.split(".")
    return (
        int(first),
        int(second),
        member.candidate.ec_level_2,
        member.candidate.accession,
        member.candidate.sequence_sha256,
    )


def _logical_manifest_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise CohortArtifactError("source dataset manifest must be a normalized logical path")
    return value


def _wrapped(sequence: str, width: int = 60) -> list[str]:
    return [sequence[index : index + width] for index in range(0, len(sequence), width)]


def serialize_selected_cohort(
    selected: SelectedCohort,
    *,
    cohort_version: str,
    selection_rule_version: str,
    source_dataset_manifest: str,
) -> SerializedCohortArtifacts:
    """Serialize provisional or reviewed cohort membership deterministically."""

    logical_manifest = _logical_manifest_path(source_dataset_manifest)
    if not cohort_version or not selection_rule_version:
        raise CohortArtifactError("cohort and selection-rule versions must be non-empty")
    members = tuple(sorted(selected.members, key=_cohort_member_key))
    rows: list[dict[str, object]] = []
    semantic_rows: list[list[object]] = []
    fasta_lines: list[str] = []
    source_hash = bytes.fromhex(selected.source_hashes.build_manifest_sha256)
    for member in members:
        candidate = member.candidate
        sequence_hash = bytes.fromhex(candidate.sequence_sha256)
        rows.append(
            {
                "accession": candidate.accession,
                "sequence_sha256": sequence_hash,
                "ec_level_2": candidate.ec_level_2,
                "sequence_length": candidate.sequence_length,
                "organism_id": candidate.organism_id,
                "discovery_component_id_cluster30": (member.discovery_component_id_cluster30),
                "source_dataset_manifest": logical_manifest,
                "source_dataset_manifest_sha256": source_hash,
                "cohort_version": cohort_version,
                "selection_rule_version": selection_rule_version,
            }
        )
        semantic_rows.append(
            [
                candidate.accession,
                candidate.sequence_sha256,
                candidate.ec_level_2,
                candidate.sequence_length,
                candidate.organism_id,
                member.discovery_component_id_cluster30,
                logical_manifest,
                selected.source_hashes.build_manifest_sha256,
                cohort_version,
                selection_rule_version,
            ]
        )
        header = (
            f">sp|{candidate.accession}|{candidate.entry_name} "
            f"ec={candidate.ec_number} taxon={candidate.organism_id} "
            f"seq_sha256={candidate.sequence_sha256}"
        )
        try:
            header.encode("ascii")
            candidate.sequence.encode("ascii")
        except UnicodeEncodeError as error:
            raise CohortArtifactError("cohort FASTA requires strict ASCII") from error
        fasta_lines.append(header)
        fasta_lines.extend(_wrapped(candidate.sequence))
    table = pa.Table.from_pylist(rows, schema=COHORT_MANIFEST_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, row_group_size=65_536, **PARQUET_WRITER_SETTINGS)
    parquet_bytes: bytes = sink.getvalue().to_pybytes()
    fasta_bytes = ("\n".join(fasta_lines) + "\n").encode("ascii") if fasta_lines else b""
    semantic_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        for row in semantic_rows
    )
    return SerializedCohortArtifacts(
        parquet_bytes=parquet_bytes,
        fasta_bytes=fasta_bytes,
        parquet_sha256=sha256_bytes(parquet_bytes),
        fasta_sha256=sha256_bytes(fasta_bytes),
        semantic_sha256=sha256_bytes(semantic_bytes),
    )


def _project_logical_path(path: Path, project_root: Path) -> str:
    try:
        resolved = path.resolve()
        root = project_root.resolve()
    except (OSError, RuntimeError) as error:
        raise CohortArtifactError("unable to resolve cohort artifact path") from error
    if resolved == root or not resolved.is_relative_to(root):
        raise CohortArtifactError("shareable cohort paths must remain inside the project")
    return resolved.relative_to(root).as_posix()


def _selection_rules(document: CohortConfigDocument) -> dict[str, str | int]:
    rules = document.config.selection
    return {
        "class_ranking": rules.class_ranking,
        "label_field": rules.label_field,
        "max_sequences_per_class": rules.max_sequences_per_class,
        "member_ranking": rules.member_ranking,
        "min_groups_per_class_at_cluster30": rules.min_groups_per_class_at_cluster30,
        "min_sequences_per_class": rules.min_sequences_per_class,
        "number_of_classes": rules.number_of_classes,
        "seed": rules.seed,
    }


def _feasibility_rules(document: CohortConfigDocument) -> dict[str, str | int]:
    feasibility = document.config.feasibility
    allocator = feasibility.allocator
    return {
        "allocator_version": allocator.version,
        "class_balance_weight": str(allocator.class_balance_weight),
        "group_count_weight": str(allocator.group_count_weight),
        "missing_class_weight": str(allocator.missing_class_weight),
        "ratio_test": str(feasibility.ratios.test),
        "ratio_tolerance": str(feasibility.ratio_tolerance),
        "ratio_train": str(feasibility.ratios.train),
        "ratio_validation": str(feasibility.ratios.validation),
        "size_weight": str(allocator.size_weight),
    }


def build_development_content_manifest(
    document: CohortConfigDocument,
    *,
    selected: SelectedCohort,
    discovery: ValidatedDiscovery,
    serialized: SerializedCohortArtifacts,
    parent_lineage: tuple[CohortParentLineage, ...],
    generation_git: GitMetadata,
    uv_lock_sha256: str,
    project_root: Path,
) -> CohortContentManifest:
    """Build a deterministic aggregate manifest that cannot claim a freeze."""

    config = document.config
    if config.run_mode != "development" or config.cohort_version != "pilot-v1-candidate":
        raise CohortArtifactError("development content requires pilot-v1-candidate config")
    selected_counts = Counter(member.candidate.ec_level_2 for member in selected.members)
    selected_components: dict[str, set[str]] = defaultdict(set)
    for member in selected.members:
        selected_components[member.candidate.ec_level_2].add(
            member.discovery_component_id_cluster30
        )
    class_summaries = tuple(
        CohortClassSummary(
            ec_level_2=decision.ec_level_2,
            eligible_rank=decision.eligible_rank,
            selected=decision.selected,
            candidate_count=decision.candidate_count,
            discovery_component_count=decision.discovery_component_count,
            selected_count=selected_counts[decision.ec_level_2],
            selected_component_count=len(selected_components[decision.ec_level_2]),
        )
        for decision in selected.eligible_ranking
    )
    reasons: list[str] = ["development_run_mode"]
    for parent in parent_lineage:
        if parent.generation_git_dirty is True:
            reasons.append(f"parent_{parent.artifact_kind}_git_dirty")
        if parent.generation_git_dirty is None or parent.generation_git_commit is None:
            reasons.append(f"parent_{parent.artifact_kind}_git_state_unknown")
    if generation_git.dirty is True:
        reasons.append("generation_git_dirty")
    if (
        not generation_git.available
        or generation_git.dirty is None
        or generation_git.commit is None
    ):
        reasons.append("generation_git_state_unknown")
    return CohortContentManifest(
        cohort_version=config.cohort_version,
        run_mode=config.run_mode,
        provisional=True,
        configuration_file=_project_logical_path(document.source_path, project_root),
        source_config_sha256=document.source_sha256,
        effective_config_sha256=document.effective_sha256,
        selection_rule_version=config.selection.selection_rule_version,
        selection_rules=_selection_rules(document),
        feasibility_rules=_feasibility_rules(document),
        selected_labels=selected.selected_labels,
        class_summaries=class_summaries,
        exclusion_reason_counts=dict(selected.exclusion_reason_counts),
        selection_evidence=("candidate_count", "discovery_component_count"),
        model_performance_used=False,
        parent_lineage=parent_lineage,
        candidate_dataset_sha256=selected.source_hashes.dataset_sha256,
        build_manifest_sha256=selected.source_hashes.build_manifest_sha256,
        candidate_fasta_sha256=selected.source_hashes.fasta_sha256,
        discovery_component_manifest_sha256=discovery.component_manifest_sha256,
        discovery_content_manifest_sha256=discovery.content_manifest_sha256,
        artifacts=CohortArtifactDigests(
            cohort_manifest=CohortArtifactDigest(
                logical_path=_project_logical_path(config.output.cohort_manifest, project_root),
                row_count=len(selected.members),
                file_sha256=serialized.parquet_sha256,
                semantic_sha256=serialized.semantic_sha256,
            ),
            fasta=CohortArtifactDigest(
                logical_path=_project_logical_path(config.output.fasta, project_root),
                row_count=len(selected.members),
                file_sha256=serialized.fasta_sha256,
                semantic_sha256=serialized.fasta_sha256,
            ),
        ),
        software_version=__version__,
        generation_git_commit=generation_git.commit,
        generation_git_dirty=generation_git.dirty,
        python_version=platform.python_version(),
        uv_lock_sha256=uv_lock_sha256,
        release_eligible=False,
        ineligibility_reasons=tuple(dict.fromkeys(reasons)),
    )


def build_frozen_content_manifest(
    document: CohortConfigDocument,
    *,
    selected: SelectedCohort,
    discovery: ValidatedDiscovery,
    serialized: SerializedCohortArtifacts,
    parent_lineage: tuple[CohortParentLineage, ...],
    generation_git: GitMetadata,
    uv_lock_sha256: str,
    project_root: Path,
) -> CohortContentManifest:
    """Build a release-eligible manifest after the external freeze gate passes."""

    config = document.config
    if config.run_mode != "freeze" or config.cohort_version != "pilot-v1":
        raise CohortArtifactError("frozen content requires pilot-v1 freeze config")
    if (
        not generation_git.available
        or generation_git.commit is None
        or generation_git.dirty is not False
    ):
        raise CohortArtifactError("frozen content requires a clean generation checkout")
    expected_kinds = ("download", "build", "discovery30", "difference", "review")
    if tuple(parent.artifact_kind for parent in parent_lineage) != expected_kinds:
        raise CohortArtifactError("frozen content requires complete reviewed parent lineage")
    if any(
        parent.generation_git_commit != generation_git.commit
        or parent.generation_git_dirty is not False
        for parent in parent_lineage
    ):
        raise CohortArtifactError("frozen parent lineage must bind the clean generation commit")
    selected_counts = Counter(member.candidate.ec_level_2 for member in selected.members)
    selected_components: dict[str, set[str]] = defaultdict(set)
    for member in selected.members:
        selected_components[member.candidate.ec_level_2].add(
            member.discovery_component_id_cluster30
        )
    class_summaries = tuple(
        CohortClassSummary(
            ec_level_2=decision.ec_level_2,
            eligible_rank=decision.eligible_rank,
            selected=decision.selected,
            candidate_count=decision.candidate_count,
            discovery_component_count=decision.discovery_component_count,
            selected_count=selected_counts[decision.ec_level_2],
            selected_component_count=len(selected_components[decision.ec_level_2]),
        )
        for decision in selected.eligible_ranking
    )
    return CohortContentManifest(
        cohort_version="pilot-v1",
        run_mode="freeze",
        provisional=False,
        configuration_file=_project_logical_path(document.source_path, project_root),
        source_config_sha256=document.source_sha256,
        effective_config_sha256=document.effective_sha256,
        selection_rule_version=config.selection.selection_rule_version,
        selection_rules=_selection_rules(document),
        feasibility_rules=_feasibility_rules(document),
        selected_labels=selected.selected_labels,
        class_summaries=class_summaries,
        exclusion_reason_counts=dict(selected.exclusion_reason_counts),
        selection_evidence=("candidate_count", "discovery_component_count"),
        model_performance_used=False,
        parent_lineage=parent_lineage,
        candidate_dataset_sha256=selected.source_hashes.dataset_sha256,
        build_manifest_sha256=selected.source_hashes.build_manifest_sha256,
        candidate_fasta_sha256=selected.source_hashes.fasta_sha256,
        discovery_component_manifest_sha256=discovery.component_manifest_sha256,
        discovery_content_manifest_sha256=discovery.content_manifest_sha256,
        artifacts=CohortArtifactDigests(
            cohort_manifest=CohortArtifactDigest(
                logical_path=_project_logical_path(config.output.cohort_manifest, project_root),
                row_count=len(selected.members),
                file_sha256=serialized.parquet_sha256,
                semantic_sha256=serialized.semantic_sha256,
            ),
            fasta=CohortArtifactDigest(
                logical_path=_project_logical_path(config.output.fasta, project_root),
                row_count=len(selected.members),
                file_sha256=serialized.fasta_sha256,
                semantic_sha256=serialized.fasta_sha256,
            ),
        ),
        software_version=__version__,
        generation_git_commit=generation_git.commit,
        generation_git_dirty=False,
        python_version=platform.python_version(),
        uv_lock_sha256=uv_lock_sha256,
        release_eligible=True,
        ineligibility_reasons=(),
    )


def _timestamp_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise CohortArtifactError("cohort run timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_cohort(
    document: CohortConfigDocument,
    *,
    project_root: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CohortBuildResult:
    """Build a provisional cohort or a fully reviewed frozen pilot-v1 cohort."""

    config = document.config
    root = project_root.resolve()
    lockfile = root / "uv.lock"
    if not lockfile.is_file():
        raise CohortArtifactError("uv.lock not found for cohort provenance")
    lineage = load_candidate_lineage(
        CandidateLineagePaths(
            raw_download=config.input.raw_download,
            download_manifest=config.input.download_manifest,
            candidate_dataset=config.input.candidate_dataset,
            candidate_fasta=config.input.candidate_fasta,
            build_manifest=config.input.build_manifest,
        ),
        require_clean=config.run_mode == "freeze",
    )
    discovery = load_discovery_partition(
        config.input.discovery_components,
        config.input.discovery_content_manifest,
        pool=lineage.pool,
    )
    selected = select_cohort(
        lineage.pool,
        discovery.partition,
        config.selection,
        config.feasibility,
    )
    serialized = serialize_selected_cohort(
        selected,
        cohort_version=config.cohort_version,
        selection_rule_version=config.selection.selection_rule_version,
        source_dataset_manifest=_project_logical_path(config.input.build_manifest, root),
    )
    generation_git = git_metadata(root)
    uv_lock_sha256 = sha256_file(lockfile)
    freeze_evidence: FreezeEvidence | None = None
    if config.run_mode == "freeze":
        try:
            difference = load_regeneration_difference_report(config.input.difference_report)
            review = FreezeReview.model_validate_json(config.input.review_attestation.read_bytes())
            freeze_evidence = validate_freeze_review(
                review,
                difference=difference,
                historical=None,
                regenerated=lineage,
                discovery=DiscoveryFreezeLineage(
                    content_manifest_sha256=discovery.content_manifest_sha256,
                    candidate_dataset_sha256=discovery.content_manifest.candidate_dataset_sha256,
                    build_manifest_sha256=discovery.content_manifest.build_manifest_sha256,
                    fasta_sha256=discovery.content_manifest.fasta_sha256,
                    generation_git_commit=discovery.content_manifest.generation_git_commit,
                    generation_git_dirty=discovery.content_manifest.generation_git_dirty,
                    uv_lock_sha256=discovery.content_manifest.uv_lock_sha256,
                    release_eligible=discovery.content_manifest.release_eligible,
                    ineligibility_reasons=discovery.content_manifest.ineligibility_reasons,
                ),
                current_git=generation_git,
                actual_uv_lock_sha256=uv_lock_sha256,
            )
        except (OSError, ValidationError, FreezeGateError, ValueError) as error:
            raise CohortArtifactError(f"pilot-v1 freeze gate failed: {error}") from error
    base_parents = (
        CohortParentLineage(
            artifact_kind="download",
            manifest_sha256=lineage.download_manifest_sha256,
            generation_git_commit=lineage.download_manifest.git_commit,
            generation_git_dirty=lineage.download_manifest.git_dirty,
        ),
        CohortParentLineage(
            artifact_kind="build",
            manifest_sha256=lineage.build_manifest_sha256,
            generation_git_commit=lineage.build_manifest.git_commit,
            generation_git_dirty=lineage.build_manifest.git_dirty,
        ),
        CohortParentLineage(
            artifact_kind="discovery30",
            manifest_sha256=discovery.content_manifest_sha256,
            generation_git_commit=discovery.content_manifest.generation_git_commit,
            generation_git_dirty=discovery.content_manifest.generation_git_dirty,
        ),
    )
    if freeze_evidence is None:
        content = build_development_content_manifest(
            document,
            selected=selected,
            discovery=discovery,
            serialized=serialized,
            parent_lineage=base_parents,
            generation_git=generation_git,
            uv_lock_sha256=uv_lock_sha256,
            project_root=root,
        )
        run_outcome = "provisional-development-cohort"
    else:
        frozen_parents = (
            *base_parents,
            CohortParentLineage(
                artifact_kind="difference",
                manifest_sha256=freeze_evidence.difference_report_sha256,
                generation_git_commit=freeze_evidence.generation_git_commit,
                generation_git_dirty=False,
            ),
            CohortParentLineage(
                artifact_kind="review",
                manifest_sha256=freeze_evidence.review_attestation_sha256,
                generation_git_commit=freeze_evidence.generation_git_commit,
                generation_git_dirty=False,
            ),
        )
        content = build_frozen_content_manifest(
            document,
            selected=selected,
            discovery=discovery,
            serialized=serialized,
            parent_lineage=frozen_parents,
            generation_git=generation_git,
            uv_lock_sha256=uv_lock_sha256,
            project_root=root,
        )
        run_outcome = "frozen-pilot-v1-cohort"
    run_provenance = config.output.run_dir / "provenance.run.json"
    run_bytes = serialize_json_mapping(
        {
            "cohort_version": config.cohort_version,
            "configuration_path": str(document.source_path),
            "generation_git_commit": generation_git.commit,
            "generation_git_dirty": generation_git.dirty,
            "outcome": run_outcome,
            "run_schema_version": 1,
            "selected_count": len(selected.members),
            "selected_labels": list(selected.selected_labels),
            "timestamp_utc": _timestamp_utc(now()),
            "uv_lock_sha256": uv_lock_sha256,
        }
    )
    try:
        publish_bundle(
            {
                config.output.cohort_manifest: serialized.parquet_bytes,
                config.output.fasta: serialized.fasta_bytes,
                config.output.content_manifest: serialize_json_model(content),
                run_provenance: run_bytes,
            }
        )
    except PublicationError as error:
        raise CohortArtifactError(f"cohort publication failed: {error}") from error
    return CohortBuildResult(
        cohort_manifest=config.output.cohort_manifest,
        fasta=config.output.fasta,
        content_manifest=config.output.content_manifest,
        run_provenance=run_provenance,
        selected_count=len(selected.members),
        selected_labels=selected.selected_labels,
        content=content,
    )


def _resolve_logical_path(value: str, project_root: Path) -> Path:
    logical = _logical_manifest_path(value)
    return project_root.resolve() / PurePosixPath(logical)


def validate_cohort_artifacts(
    cohort_manifest_path: Path,
    content_manifest_path: Path,
    *,
    project_root: Path,
) -> CohortValidationReport:
    """Reload parents and require exact deterministic cohort recomputation."""

    root = project_root.resolve()
    if not cohort_manifest_path.is_file() or not content_manifest_path.is_file():
        raise CohortArtifactError("cohort row or content manifest not found")
    try:
        content_bytes = content_manifest_path.read_bytes()
        content = CohortContentManifest.model_validate_json(content_bytes)
    except (OSError, ValueError, ValidationError) as error:
        raise CohortArtifactError("invalid cohort content manifest") from error
    if content.run_mode == "development":
        if not content.provisional or content.release_eligible:
            raise CohortArtifactError("development cohort manifest has invalid release state")
    elif content.provisional or not content.release_eligible:
        raise CohortArtifactError("frozen cohort manifest has invalid release state")
    expected_row_path = _resolve_logical_path(content.artifacts.cohort_manifest.logical_path, root)
    if cohort_manifest_path.resolve() != expected_row_path.resolve():
        raise CohortArtifactError("cohort manifest path disagrees with content manifest")
    fasta_path = _resolve_logical_path(content.artifacts.fasta.logical_path, root)
    config_path = _resolve_logical_path(content.configuration_file, root)
    if not fasta_path.is_file() or not config_path.is_file():
        raise CohortArtifactError("cohort FASTA or source configuration not found")
    document = load_cohort_config_document(config_path)
    if (
        document.source_sha256 != content.source_config_sha256
        or document.effective_sha256 != content.effective_config_sha256
    ):
        raise CohortArtifactError("cohort configuration hash mismatch")
    config = document.config
    if config.run_mode != content.run_mode or config.cohort_version != content.cohort_version:
        raise CohortArtifactError("cohort configuration mode or version disagrees with manifest")
    lineage = load_candidate_lineage(
        CandidateLineagePaths(
            raw_download=config.input.raw_download,
            download_manifest=config.input.download_manifest,
            candidate_dataset=config.input.candidate_dataset,
            candidate_fasta=config.input.candidate_fasta,
            build_manifest=config.input.build_manifest,
        ),
        require_clean=config.run_mode == "freeze",
    )
    discovery = load_discovery_partition(
        config.input.discovery_components,
        config.input.discovery_content_manifest,
        pool=lineage.pool,
    )
    selected = select_cohort(
        lineage.pool,
        discovery.partition,
        config.selection,
        config.feasibility,
    )
    serialized = serialize_selected_cohort(
        selected,
        cohort_version=config.cohort_version,
        selection_rule_version=config.selection.selection_rule_version,
        source_dataset_manifest=_project_logical_path(config.input.build_manifest, root),
    )
    if cohort_manifest_path.read_bytes() != serialized.parquet_bytes:
        raise CohortArtifactError("cohort row manifest disagrees with deterministic recomputation")
    if fasta_path.read_bytes() != serialized.fasta_bytes:
        raise CohortArtifactError("cohort FASTA disagrees with deterministic recomputation")
    base_parents = (
        CohortParentLineage(
            artifact_kind="download",
            manifest_sha256=lineage.download_manifest_sha256,
            generation_git_commit=lineage.download_manifest.git_commit,
            generation_git_dirty=lineage.download_manifest.git_dirty,
        ),
        CohortParentLineage(
            artifact_kind="build",
            manifest_sha256=lineage.build_manifest_sha256,
            generation_git_commit=lineage.build_manifest.git_commit,
            generation_git_dirty=lineage.build_manifest.git_dirty,
        ),
        CohortParentLineage(
            artifact_kind="discovery30",
            manifest_sha256=discovery.content_manifest_sha256,
            generation_git_commit=discovery.content_manifest.generation_git_commit,
            generation_git_dirty=discovery.content_manifest.generation_git_dirty,
        ),
    )
    generation_git = GitMetadata(
        available=content.generation_git_commit is not None,
        commit=content.generation_git_commit,
        dirty=content.generation_git_dirty,
    )
    if config.run_mode == "development":
        expected_content = build_development_content_manifest(
            document,
            selected=selected,
            discovery=discovery,
            serialized=serialized,
            parent_lineage=base_parents,
            generation_git=generation_git,
            uv_lock_sha256=content.uv_lock_sha256,
            project_root=root,
        )
    else:
        try:
            difference = load_regeneration_difference_report(config.input.difference_report)
            review = FreezeReview.model_validate_json(config.input.review_attestation.read_bytes())
            evidence = validate_freeze_review(
                review,
                difference=difference,
                historical=None,
                regenerated=lineage,
                discovery=DiscoveryFreezeLineage(
                    content_manifest_sha256=discovery.content_manifest_sha256,
                    candidate_dataset_sha256=discovery.content_manifest.candidate_dataset_sha256,
                    build_manifest_sha256=discovery.content_manifest.build_manifest_sha256,
                    fasta_sha256=discovery.content_manifest.fasta_sha256,
                    generation_git_commit=discovery.content_manifest.generation_git_commit,
                    generation_git_dirty=discovery.content_manifest.generation_git_dirty,
                    uv_lock_sha256=discovery.content_manifest.uv_lock_sha256,
                    release_eligible=discovery.content_manifest.release_eligible,
                    ineligibility_reasons=discovery.content_manifest.ineligibility_reasons,
                ),
                current_git=generation_git,
                actual_uv_lock_sha256=content.uv_lock_sha256,
            )
        except (OSError, ValidationError, FreezeGateError, ValueError) as error:
            raise CohortArtifactError(f"pilot-v1 validation gate failed: {error}") from error
        parents = (
            *base_parents,
            CohortParentLineage(
                artifact_kind="difference",
                manifest_sha256=evidence.difference_report_sha256,
                generation_git_commit=evidence.generation_git_commit,
                generation_git_dirty=False,
            ),
            CohortParentLineage(
                artifact_kind="review",
                manifest_sha256=evidence.review_attestation_sha256,
                generation_git_commit=evidence.generation_git_commit,
                generation_git_dirty=False,
            ),
        )
        expected_content = build_frozen_content_manifest(
            document,
            selected=selected,
            discovery=discovery,
            serialized=serialized,
            parent_lineage=parents,
            generation_git=generation_git,
            uv_lock_sha256=content.uv_lock_sha256,
            project_root=root,
        )
    if content != expected_content:
        raise CohortArtifactError("cohort content manifest disagrees with recomputation")
    return CohortValidationReport(
        cohort_version=content.cohort_version,
        provisional=content.provisional,
        selected_count=len(selected.members),
        selected_labels=selected.selected_labels,
        cohort_manifest_sha256=serialized.parquet_sha256,
        fasta_sha256=serialized.fasta_sha256,
        content_manifest_sha256=sha256_bytes(content_bytes),
    )


__all__ = [
    "COHORT_MANIFEST_SCHEMA",
    "CohortArtifactDigest",
    "CohortArtifactDigests",
    "CohortArtifactError",
    "CohortBuildResult",
    "CohortClassSummary",
    "CohortContentManifest",
    "CohortParentLineage",
    "CohortValidationReport",
    "SerializedCohortArtifacts",
    "ValidatedDiscovery",
    "build_cohort",
    "build_development_content_manifest",
    "build_frozen_content_manifest",
    "load_discovery_partition",
    "serialize_selected_cohort",
    "validate_cohort_artifacts",
]
