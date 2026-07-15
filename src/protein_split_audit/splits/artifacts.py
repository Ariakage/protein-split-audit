# SPDX-License-Identifier: Apache-2.0

"""Deterministic record-level split artifact serialization."""

from __future__ import annotations

import json
import platform
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit import __version__
from protein_split_audit.cohort.artifacts import CohortContentManifest
from protein_split_audit.config import load_split_config
from protein_split_audit.data.build_candidates import PARQUET_WRITER_SETTINGS
from protein_split_audit.provenance import (
    git_metadata,
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.publication import PublicationError, publish_bundle
from protein_split_audit.similarity.connected_components import (
    ComponentMembership,
    ComponentPartition,
)
from protein_split_audit.similarity.parse_clusters import SequenceNode
from protein_split_audit.splits.grouped_split import create_grouped_split
from protein_split_audit.splits.random_split import (
    SplitAssignment,
    SplitMember,
    create_random_split,
)
from protein_split_audit.splits.schemas import (
    SequenceStratifiedSplitConfig,
    SimilarityComponentSplitConfig,
)
from protein_split_audit.splits.validate import validate_split

SPLIT_MANIFEST_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence_sha256", pa.binary(32), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
        pa.field("similarity_component_id", pa.string(), nullable=True),
        pa.field("split_name", pa.string(), nullable=False),
        pa.field("strategy", pa.string(), nullable=False),
        pa.field("seed", pa.int64(), nullable=False),
    ]
)


@dataclass(frozen=True, slots=True)
class SerializedSplit:
    """Byte and semantic identities of one complete split manifest."""

    parquet_bytes: bytes
    file_sha256: str
    semantic_sha256: str
    row_count: int


class SplitArtifactError(RuntimeError):
    """Raised when split parents, allocation, or publication fail."""


@dataclass(frozen=True, slots=True)
class SplitArtifacts:
    """Published split artifact identities and aggregate facts."""

    manifest_path: Path
    content_manifest_path: Path
    run_provenance_path: Path
    assignment: SplitAssignment
    manifest_sha256: str
    content_manifest_sha256: str
    release_eligible: bool


def serialize_split(split: SplitAssignment) -> SerializedSplit:
    """Serialize an already validated split using explicit fixed fields."""

    rows: list[dict[str, object]] = []
    semantic: list[list[object]] = []
    for row in split.rows:
        values: dict[str, object] = {
            "accession": row.accession,
            "sequence_sha256": bytes.fromhex(row.sequence_sha256),
            "ec_level_2": row.ec_level_2,
            "split": row.split,
            "similarity_component_id": row.component_id,
            "split_name": split.name,
            "strategy": split.strategy,
            "seed": split.seed,
        }
        rows.append(values)
        semantic.append(
            [
                row.accession,
                row.sequence_sha256,
                row.ec_level_2,
                row.split,
                row.component_id,
                split.name,
                split.strategy,
                split.seed,
            ]
        )
    table = pa.Table.from_pylist(rows, schema=SPLIT_MANIFEST_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, row_group_size=65_536, **PARQUET_WRITER_SETTINGS)
    parquet_bytes: bytes = sink.getvalue().to_pybytes()
    semantic_bytes = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in semantic
    ).encode()
    return SerializedSplit(
        parquet_bytes=parquet_bytes,
        file_sha256=sha256_bytes(parquet_bytes),
        semantic_sha256=sha256_bytes(semantic_bytes),
        row_count=len(rows),
    )


def _logical(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise SplitArtifactError("shareable split path is outside the project")
    return resolved.relative_to(root).as_posix()


def _load_cohort_members(
    manifest_path: Path,
    content_path: Path,
) -> tuple[tuple[SplitMember, ...], CohortContentManifest, str]:
    try:
        content_bytes = content_path.read_bytes()
        content = CohortContentManifest.model_validate_json(content_bytes)
        table = pq.read_table(manifest_path)
    except (OSError, ValueError, pa.ArrowException) as error:
        raise SplitArtifactError("unable to load frozen cohort for splitting") from error
    if not content.release_eligible or content.provisional or content.cohort_version != "pilot-v1":
        raise SplitArtifactError("split requires a release-eligible frozen pilot-v1 cohort")
    if sha256_file(manifest_path) != content.artifacts.cohort_manifest.file_sha256:
        raise SplitArtifactError("cohort manifest hash mismatch")
    required = {"accession", "sequence_sha256", "ec_level_2"}
    if not required.issubset(table.column_names):
        raise SplitArtifactError("cohort manifest schema is incomplete")
    members = tuple(
        SplitMember(
            accession=str(row["accession"]),
            sequence_sha256=bytes(row["sequence_sha256"]).hex(),
            ec_level_2=str(row["ec_level_2"]),
        )
        for row in table.to_pylist()
    )
    return members, content, sha256_bytes(content_bytes)


def _load_components(
    manifest_path: Path,
    content_path: Path,
    members: Sequence[SplitMember],
) -> tuple[ComponentPartition, str]:
    try:
        content_bytes = content_path.read_bytes()
        content = json.loads(content_bytes)
        table = pq.read_table(manifest_path)
    except (OSError, ValueError, pa.ArrowException) as error:
        raise SplitArtifactError("unable to load formal component inputs") from error
    artifact = content.get("artifacts", {}).get("cluster_manifest", {})
    if sha256_file(manifest_path) != artifact.get("file_sha256"):
        raise SplitArtifactError("formal component manifest hash mismatch")
    if not content.get("release_eligible", False):
        raise SplitArtifactError("formal component parent is not release eligible")
    rows = table.to_pylist()
    nodes = {
        str(row["accession"]): SequenceNode(
            str(row["accession"]), bytes(row["sequence_sha256"]).hex()
        )
        for row in rows
    }
    expected = {(member.accession, member.sequence_sha256) for member in members}
    if {(node.accession, node.sequence_sha256) for node in nodes.values()} != expected:
        raise SplitArtifactError("component manifest does not exactly cover the cohort")
    memberships = tuple(
        ComponentMembership(
            node=nodes[str(row["accession"])],
            component_id=str(row["similarity_component_id"]),
            representative=nodes[str(row["similarity_component_representative"])],
            component_size=int(row["component_size"]),
        )
        for row in rows
    )
    thresholds = {Decimal(row["identity_threshold"]) for row in rows}
    if len(thresholds) != 1:
        raise SplitArtifactError("component manifest contains changing thresholds")
    return ComponentPartition(threshold=thresholds.pop(), rows=memberships), sha256_bytes(
        content_bytes
    )


def run_split(config_path: Path, *, project_root: Path) -> SplitArtifacts:
    """Create, validate, and atomically publish one configured split."""

    root = project_root.resolve()
    try:
        source_bytes = config_path.read_bytes()
        config = load_split_config(config_path)
        members, cohort_content, cohort_content_hash = _load_cohort_members(
            config.input.cohort_manifest,
            config.input.cohort_content_manifest,
        )
        component_content_hash: str | None = None
        if isinstance(config, SequenceStratifiedSplitConfig):
            assignment = create_random_split(members, seed=config.seed)
        elif isinstance(config, SimilarityComponentSplitConfig):
            components, component_content_hash = _load_components(
                config.input.component_manifest,
                config.input.component_content_manifest,
                members,
            )
            expected_threshold = {
                "cluster70": Decimal("0.70"),
                "cluster50": Decimal("0.50"),
                "cluster30": Decimal("0.30"),
            }[config.name]
            if components.threshold != expected_threshold:
                raise SplitArtifactError("split name and component threshold disagree")
            assignment = create_grouped_split(
                members,
                components,
                name=config.name,
                seed=config.seed,
            )
        else:  # pragma: no cover - the discriminated schema makes this unreachable.
            raise SplitArtifactError("unsupported split configuration")
        validation = validate_split(
            assignment,
            expected=members,
            ratio_tolerance=config.ratio_tolerance,
        )
        serialized = serialize_split(assignment)
        git = git_metadata(root)
        reasons: list[str] = []
        if config.run_mode != "freeze":
            reasons.append("development_run_mode")
        if git.dirty is not False:
            reasons.append("generation_git_not_clean")
        if cohort_content.generation_git_dirty is not False:
            reasons.append("cohort_lineage_not_clean")
        if component_content_hash is not None and isinstance(
            config, SimilarityComponentSplitConfig
        ):
            component_content = json.loads(config.input.component_content_manifest.read_bytes())
            if not component_content.get("release_eligible", False):
                reasons.append("component_lineage_not_release_eligible")
        content = {
            "manifest_schema_version": 1,
            "name": config.name,
            "strategy": config.strategy,
            "run_mode": config.run_mode,
            "configuration_file": _logical(config_path, root),
            "source_config_sha256": sha256_bytes(source_bytes),
            "cohort_content_manifest_sha256": cohort_content_hash,
            "component_content_manifest_sha256": component_content_hash,
            "seed": config.seed,
            "ratios": {"train": "0.70", "validation": "0.15", "test": "0.15"},
            "ratio_tolerance": "0.05",
            "counts": assignment.counts,
            "class_counts": assignment.class_counts,
            "validation": {
                "component_crossings": validation.component_crossings,
                "ratios": {name: f"{value:.6f}" for name, value in validation.ratios.items()},
            },
            "artifact": {
                "logical_path": _logical(config.output.manifest, root),
                "row_count": serialized.row_count,
                "file_sha256": serialized.file_sha256,
                "semantic_sha256": serialized.semantic_sha256,
            },
            "software_version": __version__,
            "generation_git_commit": git.commit,
            "generation_git_dirty": git.dirty,
            "python_version": platform.python_version(),
            "uv_lock_sha256": sha256_file(root / "uv.lock"),
            "release_eligible": not reasons,
            "ineligibility_reasons": reasons,
        }
        content_bytes = serialize_canonical_json(content)
        run_path = config.output.run_dir / "provenance.run.json"
        run_bytes = serialize_canonical_json(
            {
                "run_schema_version": 1,
                "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "outcome": "success",
                "architecture": platform.machine(),
            }
        )
        publish_bundle(
            {
                config.output.manifest: serialized.parquet_bytes,
                config.output.content_manifest: content_bytes,
                run_path: run_bytes,
            }
        )
    except (OSError, ValueError, PublicationError, pa.ArrowException) as error:
        if isinstance(error, SplitArtifactError):
            raise
        raise SplitArtifactError(f"split generation failed: {error}") from error
    return SplitArtifacts(
        manifest_path=config.output.manifest,
        content_manifest_path=config.output.content_manifest,
        run_provenance_path=run_path,
        assignment=assignment,
        manifest_sha256=serialized.file_sha256,
        content_manifest_sha256=sha256_bytes(content_bytes),
        release_eligible=not reasons,
    )


__all__: Sequence[str] = [
    "SPLIT_MANIFEST_SCHEMA",
    "SerializedSplit",
    "SplitArtifactError",
    "SplitArtifacts",
    "run_split",
    "serialize_split",
]
