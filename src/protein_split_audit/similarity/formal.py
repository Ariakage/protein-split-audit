# SPDX-License-Identifier: Apache-2.0

"""Deterministic formal similarity artifacts for a frozen cohort."""

from __future__ import annotations

import json
import platform
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit import __version__
from protein_split_audit.cohort.artifacts import CohortContentManifest
from protein_split_audit.config import SimilarityConfigDocument
from protein_split_audit.data.build_candidates import PARQUET_WRITER_SETTINGS
from protein_split_audit.provenance import (
    git_metadata,
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.publication import PublicationError, publish_bundle
from protein_split_audit.similarity.commands import (
    ClusterCommandPaths,
    SearchCommandPaths,
    build_cluster_argv,
    build_self_search_argv,
)
from protein_split_audit.similarity.connected_components import (
    ComponentPartition,
    build_components,
    validate_nested_components,
)
from protein_split_audit.similarity.discovery import serialize_discovery_rows
from protein_split_audit.similarity.mmseqs import MmseqsRunContext, run_mmseqs
from protein_split_audit.similarity.parse_clusters import (
    CandidateIndex,
    NativeClusterMembership,
    SequenceNode,
    SimilarityEdge,
    parse_native_cluster_tsv,
    parse_pair_tsv,
)
from protein_split_audit.similarity.schemas import (
    CohortClusterBaseConfig,
    CohortClusterDerivedConfig,
)

FORMAL_CLUSTER_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence_sha256", pa.binary(32), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("cluster_id", pa.string(), nullable=False),
        pa.field("cluster_representative", pa.string(), nullable=False),
        pa.field("cluster_size", pa.uint32(), nullable=False),
        pa.field("similarity_component_id", pa.string(), nullable=False),
        pa.field("similarity_component_representative", pa.string(), nullable=False),
        pa.field("component_size", pa.uint32(), nullable=False),
        pa.field("identity_threshold", pa.decimal128(3, 2), nullable=False),
        pa.field("coverage_threshold", pa.decimal128(3, 2), nullable=False),
        pa.field("mmseqs_version", pa.string(), nullable=False),
        pa.field("cohort_version", pa.string(), nullable=False),
    ]
)


class FormalSimilarityError(RuntimeError):
    """Raised when formal similarity inputs do not describe the same cohort."""


@dataclass(frozen=True, slots=True)
class SerializedFormalSimilarity:
    """Deterministic formal row artifact bytes and hashes."""

    parquet_bytes: bytes
    file_sha256: str
    semantic_sha256: str
    native_cluster_count: int
    component_count: int
    singleton_count: int
    largest_component_size: int


@dataclass(frozen=True, slots=True)
class FormalSimilarityArtifacts:
    """Published formal similarity artifacts and their strict partition."""

    cluster_manifest_path: Path
    content_manifest_path: Path
    pair_table_path: Path | None
    run_provenance_path: Path
    partition: ComponentPartition
    edges: tuple[SimilarityEdge, ...]
    content_manifest_sha256: str
    cluster_manifest_sha256: str
    pair_table_sha256: str | None


def _parquet_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    table = pa.Table.from_pylist(list(rows), schema=FORMAL_CLUSTER_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, row_group_size=65_536, **PARQUET_WRITER_SETTINGS)
    content: bytes = sink.getvalue().to_pybytes()
    return content


def serialize_formal_similarity(
    native: Sequence[NativeClusterMembership],
    partition: ComponentPartition,
    *,
    ec_level_2_by_accession: Mapping[str, str],
    mmseqs_version: str,
    cohort_version: str,
) -> SerializedFormalSimilarity:
    """Serialize descriptive native clusters and strict components without conflation."""

    if not mmseqs_version.strip() or not cohort_version.strip():
        raise FormalSimilarityError("MMseqs2 and cohort versions must be non-empty")
    strict_by_node = {row.node: row for row in partition.rows}
    native_by_node: dict[SequenceNode, NativeClusterMembership] = {}
    for row in native:
        if row.member in native_by_node:
            raise FormalSimilarityError("native cluster membership contains a duplicate member")
        native_by_node[row.member] = row
    if set(native_by_node) != set(strict_by_node):
        raise FormalSimilarityError("native clusters and strict components cover different nodes")
    accessions = {node.accession for node in strict_by_node}
    if set(ec_level_2_by_accession) != accessions:
        raise FormalSimilarityError("EC-level-2 labels do not match the cohort")

    native_sizes = Counter(row.representative for row in native_by_node.values())
    rows: list[dict[str, object]] = []
    semantic: list[list[object]] = []
    for node in sorted(strict_by_node, key=lambda item: item.accession):
        native_row = native_by_node[node]
        strict_row = strict_by_node[node]
        artifact_row: dict[str, object] = {
            "accession": node.accession,
            "sequence_sha256": bytes.fromhex(node.sequence_sha256),
            "ec_level_2": ec_level_2_by_accession[node.accession],
            "cluster_id": native_row.representative.accession,
            "cluster_representative": native_row.representative.accession,
            "cluster_size": native_sizes[native_row.representative],
            "similarity_component_id": strict_row.component_id,
            "similarity_component_representative": strict_row.representative.accession,
            "component_size": strict_row.component_size,
            "identity_threshold": partition.threshold,
            "coverage_threshold": Decimal("0.80"),
            "mmseqs_version": mmseqs_version,
            "cohort_version": cohort_version,
        }
        rows.append(artifact_row)
        semantic.append(
            [
                node.accession,
                node.sequence_sha256,
                artifact_row["ec_level_2"],
                artifact_row["cluster_id"],
                artifact_row["cluster_representative"],
                artifact_row["cluster_size"],
                artifact_row["similarity_component_id"],
                artifact_row["similarity_component_representative"],
                artifact_row["component_size"],
                format(partition.threshold, ".2f"),
                "0.80",
                mmseqs_version,
                cohort_version,
            ]
        )
    parquet_bytes = _parquet_bytes(rows)
    semantic_bytes = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in semantic
    ).encode("utf-8")
    component_sizes = Counter(row.component_id for row in partition.rows)
    return SerializedFormalSimilarity(
        parquet_bytes=parquet_bytes,
        file_sha256=sha256_bytes(parquet_bytes),
        semantic_sha256=sha256_bytes(semantic_bytes),
        native_cluster_count=len(native_sizes),
        component_count=len(component_sizes),
        singleton_count=sum(size == 1 for size in component_sizes.values()),
        largest_component_size=max(component_sizes.values()),
    )


def validate_similarity_matrix(
    p70: ComponentPartition,
    p50: ComponentPartition,
    p30: ComponentPartition,
    *,
    expected_nodes: Sequence[SequenceNode],
) -> dict[str, int]:
    """Require exact frozen-cohort coverage and 70-to-50-to-30 refinement."""

    validate_nested_components(p70, p50, p30)
    expected = set(expected_nodes)
    if len(expected) != len(tuple(expected_nodes)):
        raise FormalSimilarityError("expected cohort nodes contain duplicates")
    if any(set(partition.node_to_component) != expected for partition in (p70, p50, p30)):
        raise FormalSimilarityError("similarity matrix does not exactly cover the frozen cohort")
    return {
        "cluster70": len(set(p70.node_to_component.values())),
        "cluster50": len(set(p50.node_to_component.values())),
        "cluster30": len(set(p30.node_to_component.values())),
    }


def _logical(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise FormalSimilarityError("shareable similarity path is outside the project")
    return resolved.relative_to(root).as_posix()


def _load_cohort(
    config: CohortClusterBaseConfig | CohortClusterDerivedConfig,
) -> tuple[tuple[SequenceNode, ...], dict[str, str], CohortContentManifest, str]:
    try:
        content_bytes = config.input.cohort_content_manifest.read_bytes()
        content = CohortContentManifest.model_validate_json(content_bytes)
        table = pq.read_table(config.input.cohort_manifest)
    except (OSError, ValueError, pa.ArrowException) as error:
        raise FormalSimilarityError("unable to load frozen cohort inputs") from error
    if content.cohort_version != "pilot-v1" or not content.release_eligible or content.provisional:
        raise FormalSimilarityError("formal similarity requires release-eligible pilot-v1")
    if sha256_file(config.input.cohort_manifest) != content.artifacts.cohort_manifest.file_sha256:
        raise FormalSimilarityError("cohort row artifact hash mismatch")
    if sha256_file(config.input.fasta) != content.artifacts.fasta.file_sha256:
        raise FormalSimilarityError("cohort FASTA hash mismatch")
    required = {"accession", "sequence_sha256", "ec_level_2"}
    if not required.issubset(table.column_names):
        raise FormalSimilarityError("cohort row artifact schema is incomplete")
    rows = table.select(sorted(required)).to_pylist()
    nodes: list[SequenceNode] = []
    labels: dict[str, str] = {}
    for row in rows:
        digest = row["sequence_sha256"]
        digest_hex = digest.hex() if isinstance(digest, bytes) else str(digest)
        node = SequenceNode(str(row["accession"]), digest_hex)
        nodes.append(node)
        labels[node.accession] = str(row["ec_level_2"])
    index = CandidateIndex.from_nodes(nodes)
    return index.nodes, labels, content, sha256_bytes(content_bytes)


def _load_pair_table(path: Path, nodes: Sequence[SequenceNode]) -> tuple[SimilarityEdge, ...]:
    index = CandidateIndex.from_nodes(nodes)
    by_hash = {node.sequence_sha256: node for node in index.nodes}
    try:
        table = pq.read_table(path)
    except (OSError, pa.ArrowException) as error:
        raise FormalSimilarityError("unable to load verified base pair table") from error
    expected_columns = {
        "left_sequence_sha256",
        "right_sequence_sha256",
        "query_accession",
        "target_accession",
        "fident",
        "qcov",
        "tcov",
        "evalue",
        "bits",
    }
    if set(table.column_names) != expected_columns:
        raise FormalSimilarityError("base pair table schema is invalid")
    edges: list[SimilarityEdge] = []
    for row in table.to_pylist():
        left_hash = bytes(row["left_sequence_sha256"]).hex()
        right_hash = bytes(row["right_sequence_sha256"]).hex()
        try:
            left = by_hash[left_hash]
            right = by_hash[right_hash]
        except KeyError as error:
            raise FormalSimilarityError("base pair endpoint is outside the cohort") from error
        edges.append(
            SimilarityEdge(
                left=left,
                right=right,
                query_accession=str(row["query_accession"]),
                target_accession=str(row["target_accession"]),
                fident=Decimal(row["fident"]),
                qcov=Decimal(row["qcov"]),
                tcov=Decimal(row["tcov"]),
                evalue=Decimal(str(row["evalue"])),
                bits=Decimal(str(row["bits"])),
            )
        )
    return tuple(edges)


def _run_cluster(
    config: CohortClusterBaseConfig | CohortClusterDerivedConfig,
    *,
    sequence_count: int,
    completed_outputs: Sequence[Path],
) -> tuple[tuple[NativeClusterMembership, ...], str, tuple[str, ...], Path]:
    run = MmseqsRunContext.create(
        cache_root=config.runtime.cache_root,
        timeout_seconds=config.runtime.timeout_seconds,
        expected_output_names=("cluster_cluster.tsv",),
        completed_outputs=completed_outputs,
    )
    argv = build_cluster_argv(
        config.cluster,
        config.runtime,
        sequence_count,
        paths=ClusterCommandPaths(
            input_fasta=config.input.fasta,
            output_prefix=run.staging_dir / "cluster",
            temp_dir=run.staging_dir / "tmp",
        ),
    )
    result = run_mmseqs(argv, run)
    return (), result.mmseqs_version, result.sanitized_argv, result.outputs[0]


def _run_formal_similarity(
    document: SimilarityConfigDocument,
    *,
    project_root: Path,
) -> FormalSimilarityArtifacts:
    config = document.config
    if not isinstance(config, (CohortClusterBaseConfig, CohortClusterDerivedConfig)):
        raise FormalSimilarityError("configuration is not a formal cohort similarity operation")
    root = project_root.resolve()
    nodes, labels, cohort_content, cohort_content_sha256 = _load_cohort(config)
    run_path = config.output.run_dir / "provenance.run.json"
    pair_output = config.output.pair_table if isinstance(config, CohortClusterBaseConfig) else None
    outputs = tuple(
        path
        for path in (
            config.output.cluster_manifest,
            config.output.content_manifest,
            pair_output,
            run_path,
        )
        if path is not None
    )
    cluster_run = MmseqsRunContext.create(
        cache_root=config.runtime.cache_root,
        timeout_seconds=config.runtime.timeout_seconds,
        expected_output_names=("cluster_cluster.tsv",),
        completed_outputs=outputs,
    )
    cluster_argv = build_cluster_argv(
        config.cluster,
        config.runtime,
        len(nodes),
        paths=ClusterCommandPaths(
            input_fasta=config.input.fasta,
            output_prefix=cluster_run.staging_dir / "cluster",
            temp_dir=cluster_run.staging_dir / "tmp",
        ),
    )
    try:
        cluster_result = run_mmseqs(cluster_argv, cluster_run)
        index = CandidateIndex.from_nodes(nodes)
        native = parse_native_cluster_tsv(cluster_result.outputs[0], index)
        if isinstance(config, CohortClusterBaseConfig):
            search_run = MmseqsRunContext.create(
                cache_root=config.runtime.cache_root,
                timeout_seconds=config.runtime.timeout_seconds,
                expected_output_names=("pairs.tsv",),
                completed_outputs=outputs,
            )
            search_argv = build_self_search_argv(
                config.self_search,
                config.runtime,
                len(nodes),
                paths=SearchCommandPaths(
                    query_fasta=config.input.fasta,
                    target_fasta=config.input.fasta,
                    output_tsv=search_run.expected_outputs[0],
                    temp_dir=search_run.staging_dir / "tmp",
                ),
            )
            search_result = run_mmseqs(search_argv, search_run)
            if search_result.mmseqs_version != cluster_result.mmseqs_version:
                raise FormalSimilarityError("MMseqs2 version changed during formal grouping")
            edges = parse_pair_tsv(search_result.outputs[0], index)
            search_command: tuple[str, ...] | None = search_result.sanitized_argv
        else:
            if sha256_file(config.input.base_pair_table) != config.input.base_pair_sha256:
                raise FormalSimilarityError("base pair table hash does not match configuration")
            base_content_hash = sha256_file(config.input.base_pair_content_manifest)
            base_content = json.loads(config.input.base_pair_content_manifest.read_bytes())
            if (
                base_content.get("artifacts", {}).get("pair_table", {}).get("file_sha256")
                != config.input.base_pair_sha256
            ):
                raise FormalSimilarityError("base content manifest does not bind the pair table")
            if base_content_hash == cohort_content_sha256:
                raise FormalSimilarityError("base content manifest identity is invalid")
            edges = _load_pair_table(config.input.base_pair_table, nodes)
            search_command = None
            search_run = None
        partition = build_components(
            nodes, edges, Decimal(str(config.cluster.min_sequence_identity))
        )
        serialized = serialize_formal_similarity(
            native,
            partition,
            ec_level_2_by_accession=labels,
            mmseqs_version=cluster_result.mmseqs_version,
            cohort_version=cohort_content.cohort_version,
        )
        pair_bytes: bytes | None = None
        pair_hash: str | None = None
        pair_semantic_hash: str | None = None
        if isinstance(config, CohortClusterBaseConfig):
            pair_rows = serialize_discovery_rows(
                edges,
                partition,
                ec_level_2_by_accession=labels,
                mmseqs_version=cluster_result.mmseqs_version,
            )
            pair_bytes = pair_rows.pair_table_bytes
            pair_hash = pair_rows.pair_table_sha256
            pair_semantic_hash = pair_rows.pair_table_semantic_sha256
        git = git_metadata(root)
        lock_hash = sha256_file(root / "uv.lock")
        state_reasons = []
        if git.dirty is not False:
            state_reasons.append("generation_git_not_clean")
        if cohort_content.generation_git_dirty is not False:
            state_reasons.append("cohort_lineage_not_clean")
        if config.run_mode != "freeze":
            state_reasons.append("development_run_mode")
        artifacts: dict[str, object] = {
            "cluster_manifest": {
                "logical_path": _logical(config.output.cluster_manifest, root),
                "row_count": len(nodes),
                "file_sha256": serialized.file_sha256,
                "semantic_sha256": serialized.semantic_sha256,
            }
        }
        if pair_output is not None and pair_hash is not None and pair_semantic_hash is not None:
            artifacts["pair_table"] = {
                "logical_path": _logical(pair_output, root),
                "row_count": len(edges),
                "file_sha256": pair_hash,
                "semantic_sha256": pair_semantic_hash,
            }
        content = {
            "manifest_schema_version": 1,
            "operation": config.operation,
            "name": config.name,
            "run_mode": config.run_mode,
            "configuration_file": _logical(document.source_path, root),
            "source_config_sha256": document.source_sha256,
            "effective_config_sha256": document.effective_sha256,
            "cohort_content_manifest_sha256": cohort_content_sha256,
            "cohort_manifest_sha256": sha256_file(config.input.cohort_manifest),
            "cohort_fasta_sha256": sha256_file(config.input.fasta),
            "base_pair_table_sha256": (
                None
                if isinstance(config, CohortClusterBaseConfig)
                else config.input.base_pair_sha256
            ),
            "identity_threshold": f"{config.cluster.min_sequence_identity:.2f}",
            "coverage_threshold": f"{config.cluster.minimum_coverage:.2f}",
            "mmseqs_version": cluster_result.mmseqs_version,
            "commands": {"cluster": cluster_result.sanitized_argv, "self_search": search_command},
            "counts": {
                "sequence_count": len(nodes),
                "native_cluster_count": serialized.native_cluster_count,
                "strict_component_count": serialized.component_count,
                "singleton_count": serialized.singleton_count,
                "largest_component_size": serialized.largest_component_size,
                "pair_count": len(edges),
            },
            "artifacts": artifacts,
            "software_version": __version__,
            "generation_git_commit": git.commit,
            "generation_git_dirty": git.dirty,
            "python_version": platform.python_version(),
            "uv_lock_sha256": lock_hash,
            "release_eligible": not state_reasons,
            "ineligibility_reasons": state_reasons,
        }
        content_bytes = serialize_canonical_json(content)
        run_bytes = serialize_canonical_json(
            {
                "run_schema_version": 1,
                "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "architecture": platform.machine(),
                "cluster_staging_dir": str(cluster_run.staging_dir),
                "search_staging_dir": None if search_run is None else str(search_run.staging_dir),
                "outcome": "success",
            }
        )
        shutil.rmtree(cluster_run.staging_dir)
        if search_run is not None:
            shutil.rmtree(search_run.staging_dir)
        bundle = {
            config.output.cluster_manifest: serialized.parquet_bytes,
            config.output.content_manifest: content_bytes,
            run_path: run_bytes,
        }
        if pair_output is not None and pair_bytes is not None:
            bundle[pair_output] = pair_bytes
        publish_bundle(bundle)
    except (OSError, ValueError, PublicationError, pa.ArrowException) as error:
        raise FormalSimilarityError(f"formal similarity generation failed: {error}") from error
    return FormalSimilarityArtifacts(
        cluster_manifest_path=config.output.cluster_manifest,
        content_manifest_path=config.output.content_manifest,
        pair_table_path=pair_output,
        run_provenance_path=run_path,
        partition=partition,
        edges=tuple(edges),
        content_manifest_sha256=sha256_bytes(content_bytes),
        cluster_manifest_sha256=serialized.file_sha256,
        pair_table_sha256=pair_hash,
    )


def build_base_similarity(
    document: SimilarityConfigDocument,
    *,
    project_root: Path,
) -> FormalSimilarityArtifacts:
    """Build Cluster30 native clusters, base pair table, and strict components."""

    if not isinstance(document.config, CohortClusterBaseConfig):
        raise FormalSimilarityError("base similarity requires cohort_cluster_base configuration")
    return _run_formal_similarity(document, project_root=project_root)


def derive_similarity(
    document: SimilarityConfigDocument,
    *,
    project_root: Path,
) -> FormalSimilarityArtifacts:
    """Build Cluster50 or Cluster70 from the verified base pair table."""

    if not isinstance(document.config, CohortClusterDerivedConfig):
        raise FormalSimilarityError("derived similarity requires cohort_cluster_derived config")
    return _run_formal_similarity(document, project_root=project_root)


__all__ = [
    "FORMAL_CLUSTER_SCHEMA",
    "FormalSimilarityArtifacts",
    "FormalSimilarityError",
    "SerializedFormalSimilarity",
    "build_base_similarity",
    "derive_similarity",
    "serialize_formal_similarity",
    "validate_similarity_matrix",
]
