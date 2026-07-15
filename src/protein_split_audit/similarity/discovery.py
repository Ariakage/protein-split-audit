# SPDX-License-Identifier: Apache-2.0

"""Candidate-pool similarity discovery orchestration and artifacts."""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit import __version__
from protein_split_audit.cohort.profile_cohort import CandidateProfileError, load_candidate_pool
from protein_split_audit.config import SimilarityConfigDocument
from protein_split_audit.data.build_candidates import PARQUET_WRITER_SETTINGS
from protein_split_audit.paths import find_project_root
from protein_split_audit.provenance import (
    GitMetadata,
    git_metadata,
    serialize_canonical_json,
    serialize_json_model,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.publication import PublicationError, publish_bundle
from protein_split_audit.similarity.commands import SearchCommandPaths, build_self_search_argv
from protein_split_audit.similarity.connected_components import (
    ComponentError,
    ComponentPartition,
    build_components,
)
from protein_split_audit.similarity.mmseqs import (
    MmseqsProbeError,
    MmseqsRunContext,
    MmseqsRunError,
    MmseqsRunResult,
    run_mmseqs,
)
from protein_split_audit.similarity.parse_clusters import (
    CandidateIndex,
    PairTsvError,
    SequenceNode,
    SimilarityEdge,
    parse_pair_tsv,
)
from protein_split_audit.similarity.schemas import (
    CandidateDiscoveryArtifactDigests,
    CandidateDiscoveryCommand,
    CandidateDiscoveryConfig,
    CandidateDiscoveryContentManifest,
    CandidateDiscoveryCounts,
    CandidateDiscoveryFailureProvenance,
    CandidateDiscoveryRunProvenance,
    MmseqsRuntimeConfig,
    SimilarityArtifactDigest,
    SimilarityParentLineage,
)

PAIR_TABLE_SCHEMA = pa.schema(
    [
        pa.field("left_sequence_sha256", pa.binary(32), nullable=False),
        pa.field("right_sequence_sha256", pa.binary(32), nullable=False),
        pa.field("query_accession", pa.string(), nullable=False),
        pa.field("target_accession", pa.string(), nullable=False),
        pa.field("fident", pa.decimal128(7, 6), nullable=False),
        pa.field("qcov", pa.decimal128(7, 6), nullable=False),
        pa.field("tcov", pa.decimal128(7, 6), nullable=False),
        pa.field("evalue", pa.float64(), nullable=False),
        pa.field("bits", pa.float64(), nullable=False),
    ]
)

COMPONENT_MANIFEST_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence_sha256", pa.binary(32), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("similarity_component_id", pa.string(), nullable=False),
        pa.field("similarity_component_representative", pa.string(), nullable=False),
        pa.field("component_size", pa.uint32(), nullable=False),
        pa.field("identity_threshold", pa.decimal128(3, 2), nullable=False),
        pa.field("coverage_threshold", pa.decimal128(3, 2), nullable=False),
        pa.field("mmseqs_version", pa.string(), nullable=False),
    ]
)


class DiscoveryError(RuntimeError):
    """Raised when candidate discovery cannot complete safely."""


@dataclass(frozen=True, slots=True)
class SerializedDiscoveryRows:
    """Deterministic row artifact bytes and their file/semantic hashes."""

    pair_table_bytes: bytes
    component_manifest_bytes: bytes
    pair_table_sha256: str
    component_manifest_sha256: str
    pair_table_semantic_sha256: str
    component_manifest_semantic_sha256: str


@dataclass(frozen=True, slots=True)
class SimilarityArtifacts:
    """Published candidate-discovery artifacts and aggregate result counts."""

    pair_table_path: Path
    component_manifest_path: Path
    content_manifest_path: Path
    run_provenance_path: Path
    published_paths: tuple[Path, ...]
    content_manifest: CandidateDiscoveryContentManifest
    sequence_count: int
    edge_count: int
    component_count: int
    singleton_count: int
    largest_component_size: int


class DiscoveryRunContextFactory(Protocol):
    """Create one Task 3 run context without coupling tests to a real executable."""

    def __call__(
        self,
        *,
        runtime: MmseqsRuntimeConfig,
        expected_output_name: str,
        completed_outputs: Sequence[Path],
    ) -> MmseqsRunContext: ...


_SIX_PLACES = Decimal("0.000001")
_TWO_PLACES = Decimal("0.01")
_COVERAGE_THRESHOLD = Decimal("0.80")
_FAILURE_STDERR_LIMIT = 4096
_LOWER_HEX = frozenset("0123456789abcdef")


def _fixed_decimal(value: Decimal, quantum: Decimal) -> Decimal:
    try:
        fixed = value.quantize(quantum)
    except InvalidOperation as error:
        raise DiscoveryError("similarity metric cannot be represented exactly") from error
    if fixed != value:
        raise DiscoveryError("similarity metric exceeds the artifact decimal precision")
    return fixed


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _finite_float(value: Decimal) -> float:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DiscoveryError("similarity metric must be a finite Decimal")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as error:
        raise DiscoveryError("similarity metric must have a finite float representation") from error
    if not math.isfinite(converted):
        raise DiscoveryError("similarity metric must have a finite float representation")
    return converted


def _semantic_bytes(rows: Sequence[Sequence[object]]) -> bytes:
    return "".join(
        json.dumps(list(row), ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    ).encode("utf-8")


def _parquet_bytes(rows: Sequence[Mapping[str, object]], schema: pa.Schema) -> bytes:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        row_group_size=65_536,
        **PARQUET_WRITER_SETTINGS,
    )
    content: bytes = sink.getvalue().to_pybytes()
    return content


def serialize_discovery_rows(
    edges: Sequence[SimilarityEdge],
    partition: ComponentPartition,
    *,
    ec_level_2_by_accession: Mapping[str, str],
    mmseqs_version: str,
) -> SerializedDiscoveryRows:
    """Serialize normalized pair edges and one component partition deterministically."""

    if not mmseqs_version.strip():
        raise DiscoveryError("MMseqs2 version must be non-empty")
    accessions = {row.node.accession for row in partition.rows}
    if set(ec_level_2_by_accession) != accessions:
        raise DiscoveryError("EC-level-2 labels do not match the component partition")

    partition_nodes = {row.node for row in partition.rows}
    seen_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.left not in partition_nodes or edge.right not in partition_nodes:
            raise DiscoveryError("similarity edge endpoint is outside the component partition")
        if edge.left == edge.right:
            raise DiscoveryError("similarity edge must have two distinct endpoints")
        pair = tuple(sorted((edge.left.sequence_sha256, edge.right.sequence_sha256)))
        pair_key = (pair[0], pair[1])
        if pair_key in seen_pairs:
            raise DiscoveryError("similarity rows contain a duplicate undirected edge")
        seen_pairs.add(pair_key)
        if edge.query_accession == edge.target_accession or {
            edge.query_accession,
            edge.target_accession,
        } != {edge.left.accession, edge.right.accession}:
            raise DiscoveryError("similarity edge query/target do not match its endpoints")

    pair_rows: list[dict[str, object]] = []
    pair_semantic_rows: list[list[object]] = []
    ordered_edges = sorted(
        edges,
        key=lambda edge: (
            min(edge.left.sequence_sha256, edge.right.sequence_sha256),
            max(edge.left.sequence_sha256, edge.right.sequence_sha256),
        ),
    )
    for edge in ordered_edges:
        left, right = sorted(
            (edge.left, edge.right),
            key=lambda node: node.sequence_sha256,
        )
        fident = _fixed_decimal(edge.fident, _SIX_PLACES)
        qcov = _fixed_decimal(edge.qcov, _SIX_PLACES)
        tcov = _fixed_decimal(edge.tcov, _SIX_PLACES)
        evalue = _finite_float(edge.evalue)
        bits = _finite_float(edge.bits)
        pair_rows.append(
            {
                "left_sequence_sha256": bytes.fromhex(left.sequence_sha256),
                "right_sequence_sha256": bytes.fromhex(right.sequence_sha256),
                "query_accession": edge.query_accession,
                "target_accession": edge.target_accession,
                "fident": fident,
                "qcov": qcov,
                "tcov": tcov,
                "evalue": evalue,
                "bits": bits,
            }
        )
        pair_semantic_rows.append(
            [
                left.sequence_sha256,
                right.sequence_sha256,
                edge.query_accession,
                edge.target_accession,
                format(fident, ".6f"),
                format(qcov, ".6f"),
                format(tcov, ".6f"),
                _canonical_decimal(edge.evalue),
                _canonical_decimal(edge.bits),
            ]
        )

    identity_threshold = _fixed_decimal(partition.threshold, _TWO_PLACES)
    coverage_threshold = _COVERAGE_THRESHOLD
    component_rows: list[dict[str, object]] = []
    component_semantic_rows: list[list[object]] = []
    for membership in sorted(
        partition.rows,
        key=lambda row: (row.component_id, row.node.accession),
    ):
        label = ec_level_2_by_accession[membership.node.accession]
        component_rows.append(
            {
                "accession": membership.node.accession,
                "sequence_sha256": bytes.fromhex(membership.node.sequence_sha256),
                "ec_level_2": label,
                "similarity_component_id": membership.component_id,
                "similarity_component_representative": membership.representative.accession,
                "component_size": membership.component_size,
                "identity_threshold": identity_threshold,
                "coverage_threshold": coverage_threshold,
                "mmseqs_version": mmseqs_version,
            }
        )
        component_semantic_rows.append(
            [
                membership.node.accession,
                membership.node.sequence_sha256,
                label,
                membership.component_id,
                membership.representative.accession,
                membership.component_size,
                format(identity_threshold, ".2f"),
                format(coverage_threshold, ".2f"),
                mmseqs_version,
            ]
        )

    pair_table_bytes = _parquet_bytes(pair_rows, PAIR_TABLE_SCHEMA)
    component_manifest_bytes = _parquet_bytes(component_rows, COMPONENT_MANIFEST_SCHEMA)
    pair_semantic_bytes = _semantic_bytes(pair_semantic_rows)
    component_semantic_bytes = _semantic_bytes(component_semantic_rows)
    return SerializedDiscoveryRows(
        pair_table_bytes=pair_table_bytes,
        component_manifest_bytes=component_manifest_bytes,
        pair_table_sha256=sha256_bytes(pair_table_bytes),
        component_manifest_sha256=sha256_bytes(component_manifest_bytes),
        pair_table_semantic_sha256=sha256_bytes(pair_semantic_bytes),
        component_manifest_semantic_sha256=sha256_bytes(component_semantic_bytes),
    )


def create_discovery_run_context(
    *,
    runtime: MmseqsRuntimeConfig,
    expected_output_name: str,
    completed_outputs: Sequence[Path],
) -> MmseqsRunContext:
    """Create the production Task 3 context for one candidate discovery search."""

    return MmseqsRunContext.create(
        cache_root=runtime.cache_root,
        timeout_seconds=runtime.timeout_seconds,
        expected_output_names=(expected_output_name,),
        completed_outputs=completed_outputs,
    )


def _project_logical_path(path: Path, project_root: Path) -> str:
    if not path.is_absolute():
        raise DiscoveryError("shareable candidate discovery paths must be project-relative")
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as error:
        raise DiscoveryError("unable to resolve a shareable candidate discovery path") from error
    if not resolved.is_relative_to(project_root) or resolved == project_root:
        raise DiscoveryError("shareable candidate discovery paths must remain in the project tree")
    return resolved.relative_to(project_root).as_posix()


def _path_lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise DiscoveryError("unable to inspect a candidate discovery output") from error
    return True


def _reset_staging(staging_dir: Path, *, retain: bool) -> bool:
    try:
        shutil.rmtree(staging_dir)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    if retain:
        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
        except OSError:
            return False
    return True


def _safe_regular_output(path: Path, staging_dir: Path) -> bool:
    try:
        status = path.lstat()
        resolved = path.resolve(strict=True)
        resolved_stage = staging_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return (
        stat.S_ISREG(status.st_mode)
        and not path.is_symlink()
        and resolved.is_relative_to(resolved_stage)
    )


def _timestamp_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise DiscoveryError("candidate discovery timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounded_tail(value: str, limit: int = _FAILURE_STDERR_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return "…" + value[-(limit - 1) :]


def _write_failure_provenance(staging_dir: Path, content: bytes) -> None:
    path = staging_dir / "provenance.failure.json"
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _retain_failure_provenance(
    *,
    error: DiscoveryError,
    failure_stage: str,
    run: MmseqsRunContext,
    run_result: MmseqsRunResult | None,
    started_at_utc: str,
    ended_at_utc: str,
    configured_threads: int,
) -> None:
    cleanup_succeeded = _reset_staging(run.staging_dir, retain=True)
    if not cleanup_succeeded:
        return

    mmseqs_error: MmseqsRunError | None = None
    probe_error: MmseqsProbeError | None = None
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, MmseqsRunError):
            mmseqs_error = cause
            break
        if isinstance(cause, MmseqsProbeError):
            probe_error = cause
            break
        cause = cause.__cause__

    resolved_executable = (
        run_result.resolved_executable
        if run_result is not None
        else mmseqs_error.resolved_executable
        if mmseqs_error is not None
        else probe_error.executable
        if probe_error is not None
        else None
    )
    provenance = CandidateDiscoveryFailureProvenance(
        started_at_utc=started_at_utc,
        ended_at_utc=ended_at_utc,
        failure_stage=failure_stage,
        failure_reason=_bounded_tail(str(error), 512),
        resolved_executable=(str(resolved_executable) if resolved_executable is not None else None),
        mmseqs_version=(
            run_result.mmseqs_version
            if run_result is not None
            else mmseqs_error.mmseqs_version
            if mmseqs_error is not None
            else None
        ),
        staging_dir=str(run.staging_dir),
        architecture=platform.machine(),
        logical_cpu_count=os.cpu_count(),
        configured_threads=configured_threads,
        sanitized_argv=(
            run_result.sanitized_argv
            if run_result is not None
            else mmseqs_error.sanitized_argv
            if mmseqs_error is not None
            else ()
        ),
        returncode=(
            run_result.returncode
            if run_result is not None
            else mmseqs_error.returncode
            if mmseqs_error is not None
            else None
        ),
        timed_out=mmseqs_error.timed_out if mmseqs_error is not None else False,
        stderr_tail=_bounded_tail(
            run_result.stderr_tail
            if run_result is not None
            else mmseqs_error.stderr_tail
            if mmseqs_error is not None
            else ""
        ),
        runner_cleanup_succeeded=(
            mmseqs_error.cleanup_succeeded if mmseqs_error is not None else None
        ),
        cleanup_succeeded=cleanup_succeeded,
    )
    _write_failure_provenance(run.staging_dir, serialize_json_model(provenance))


def _record_failure_best_effort(
    *,
    error: DiscoveryError,
    failure_stage: str,
    run: MmseqsRunContext,
    run_result: MmseqsRunResult | None,
    started_at_utc: str,
    now: Callable[[], datetime],
    configured_threads: int,
) -> None:
    """Retain local failure evidence without ever replacing the primary error."""

    try:
        ended_at_utc = _timestamp_utc(now())
    except Exception:  # A diagnostic timestamp must never mask the primary failure.
        ended_at_utc = started_at_utc
    try:
        _retain_failure_provenance(
            error=error,
            failure_stage=failure_stage,
            run=run,
            run_result=run_result,
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at_utc,
            configured_threads=configured_threads,
        )
    except Exception:  # Failure evidence is deliberately best effort.
        return


def _state_reasons(
    parent_commit: str | None, parent_dirty: bool | None, git: GitMetadata
) -> list[str]:
    reasons: list[str] = []
    if parent_dirty is True:
        reasons.append("parent_git_dirty")
    if parent_dirty is None or parent_commit is None:
        reasons.append("parent_git_state_unknown")
    if git.dirty is True:
        reasons.append("generation_git_dirty")
    if not git.available or git.dirty is None or git.commit is None:
        reasons.append("generation_git_state_unknown")
    return reasons


def _is_valid_git_commit(value: str) -> bool:
    return len(value) == 40 and all(character in _LOWER_HEX for character in value)


def _verify_candidate_input_hashes(
    expected_inputs: Sequence[tuple[str, Path, str]],
) -> None:
    for label, path, expected_sha256 in expected_inputs:
        try:
            actual_sha256 = sha256_file(path)
        except OSError as error:
            raise DiscoveryError("candidate input reconciliation failed") from error
        if actual_sha256 != expected_sha256:
            raise DiscoveryError(f"candidate {label} input changed during discovery")


def _fixed_parameters(config: CandidateDiscoveryConfig) -> dict[str, str | int | bool]:
    search = config.self_search
    return {
        "alignment_mode": search.alignment_mode,
        "coverage_mode": search.coverage_mode,
        "evalue": f"{search.evalue:g}",
        "format_mode": search.format_mode,
        "min_sequence_identity": f"{search.min_sequence_identity:.2f}",
        "minimum_coverage": f"{search.minimum_coverage:.2f}",
        "search_type": search.search_type,
        "sensitivity": f"{search.sensitivity:g}",
        "sequence_identity_mode": search.sequence_identity_mode,
        "threads": config.runtime.threads,
    }


def _aggregate_counts(
    partition: ComponentPartition,
    edges: Sequence[SimilarityEdge],
    labels: Mapping[str, str],
) -> CandidateDiscoveryCounts:
    component_sizes: dict[str, int] = {}
    class_components: dict[str, set[str]] = {}
    for row in partition.rows:
        component_sizes[row.component_id] = row.component_size
        class_components.setdefault(labels[row.node.accession], set()).add(row.component_id)
    return CandidateDiscoveryCounts(
        sequence_count=len(partition.rows),
        edge_count=len(edges),
        component_count=len(component_sizes),
        singleton_count=sum(size == 1 for size in component_sizes.values()),
        largest_component_size=max(component_sizes.values()),
        per_class_component_counts={
            label: len(component_ids) for label, component_ids in sorted(class_components.items())
        },
    )


def discover_candidate_pool(
    document: SimilarityConfigDocument,
    *,
    run_context_factory: DiscoveryRunContextFactory,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    project_root: Path | None = None,
) -> SimilarityArtifacts:
    """Run and publish one verified 30% candidate-pool discovery operation."""

    config = document.config
    if not isinstance(config, CandidateDiscoveryConfig):
        raise DiscoveryError("similarity configuration is not a candidate discovery operation")
    root = (
        project_root.resolve()
        if project_root is not None
        else find_project_root(document.source_path)
    )
    if root is None:
        raise DiscoveryError("project root not found for candidate discovery")
    root = root.resolve()
    started_at = _timestamp_utc(now())
    run_provenance_path = config.output.run_dir / "provenance.run.json"
    configured_outputs = (
        config.output.pair_table,
        config.output.component_manifest,
        config.output.content_manifest,
        run_provenance_path,
    )
    configuration_file = _project_logical_path(document.source_path, root)
    pair_table_logical_path = _project_logical_path(config.output.pair_table, root)
    component_manifest_logical_path = _project_logical_path(
        config.output.component_manifest,
        root,
    )
    for output_path in configured_outputs:
        _project_logical_path(output_path, root)
    if any(_path_lexists(path) for path in configured_outputs):
        raise DiscoveryError("refusing to overwrite a candidate discovery artifact")

    try:
        pool = load_candidate_pool(
            config.input.candidate_dataset,
            config.input.build_manifest,
            config.input.fasta,
        )
    except CandidateProfileError as error:
        raise DiscoveryError(f"candidate input validation failed: {error}") from error
    if not pool.records:
        raise DiscoveryError("candidate discovery requires a non-empty candidate pool")

    lockfile = root / "uv.lock"
    if not lockfile.is_file():
        raise DiscoveryError("uv.lock not found for candidate discovery provenance")
    try:
        uv_lock_sha256 = sha256_file(lockfile)
    except OSError as error:
        raise DiscoveryError("unable to hash uv.lock for candidate discovery") from error

    generation_git = git_metadata(root)
    if (
        pool.build_manifest.git_commit is not None
        and not _is_valid_git_commit(pool.build_manifest.git_commit)
    ) or (generation_git.commit is not None and not _is_valid_git_commit(generation_git.commit)):
        raise DiscoveryError("candidate discovery has invalid Git commit provenance")
    state_reasons = _state_reasons(
        pool.build_manifest.git_commit,
        pool.build_manifest.git_dirty,
        generation_git,
    )
    if config.run_mode == "freeze" and state_reasons:
        raise DiscoveryError("freeze candidate discovery requires clean known Git lineage")
    ineligibility_reasons = (
        ("development_run_mode", *state_reasons) if config.run_mode == "development" else ()
    )

    nodes = tuple(
        SequenceNode(accession=record.accession, sequence_sha256=record.sequence_sha256)
        for record in pool.records
    )
    labels = {record.accession: record.ec_level_2 for record in pool.records}
    expected_inputs = (
        ("dataset", config.input.candidate_dataset, pool.dataset_sha256),
        ("build manifest", config.input.build_manifest, pool.build_manifest_sha256),
        ("FASTA", config.input.fasta, pool.fasta_sha256),
    )
    try:
        run = run_context_factory(
            runtime=config.runtime,
            expected_output_name="pairs.tsv",
            completed_outputs=configured_outputs,
        )
    except (OSError, ValueError) as error:
        raise DiscoveryError("unable to create candidate discovery staging context") from error

    try:
        run_result: MmseqsRunResult | None = None
        failure_stage = "input_reconciliation"
        _verify_candidate_input_hashes(expected_inputs)
        failure_stage = "command_construction"
        paths = SearchCommandPaths(
            query_fasta=config.input.fasta,
            target_fasta=config.input.fasta,
            output_tsv=run.expected_outputs[0],
            temp_dir=run.staging_dir / "tmp",
        )
        argv = build_self_search_argv(
            config.self_search,
            config.runtime,
            len(nodes),
            paths=paths,
        )
        failure_stage = "mmseqs_execution"
        try:
            run_result = run_mmseqs(argv, run)
        except (MmseqsProbeError, MmseqsRunError) as error:
            raise DiscoveryError("MMseqs2 candidate discovery execution failed") from error
        failure_stage = "input_reconciliation"
        _verify_candidate_input_hashes(expected_inputs)
        failure_stage = "staged_output_validation"
        if (
            len(run_result.outputs) != 1
            or run_result.outputs[0] != run.expected_outputs[0]
            or not _safe_regular_output(run_result.outputs[0], run.staging_dir)
        ):
            raise DiscoveryError("MMseqs2 candidate discovery output is not a safe staged TSV")
        raw_pair_tsv_sha256 = sha256_file(run_result.outputs[0])
        failure_stage = "pair_validation"
        try:
            index = CandidateIndex.from_nodes(nodes)
            edges = parse_pair_tsv(run_result.outputs[0], index)
            if any(edge.fident < Decimal("0.30") for edge in edges):
                raise DiscoveryError(
                    "candidate discovery pair violates the fixed 30% identity predicate"
                )
            partition = build_components(nodes, edges, Decimal("0.30"))
        except (PairTsvError, ComponentError, ValueError) as error:
            raise DiscoveryError("candidate discovery output validation failed") from error
        failure_stage = "row_serialization"
        try:
            row_artifacts = serialize_discovery_rows(
                edges,
                partition,
                ec_level_2_by_accession=labels,
                mmseqs_version=run_result.mmseqs_version,
            )
        except (DiscoveryError, OSError, ValueError, pa.ArrowException) as error:
            raise DiscoveryError("candidate discovery row serialization failed") from error

        failure_stage = "input_reconciliation"
        _verify_candidate_input_hashes(expected_inputs)
        failure_stage = "content_manifest"
        counts = _aggregate_counts(partition, edges, labels)
        content_manifest = CandidateDiscoveryContentManifest(
            operation=config.operation,
            name=config.name,
            run_mode=config.run_mode,
            configuration_file=configuration_file,
            source_config_sha256=document.source_sha256,
            effective_config_sha256=document.effective_sha256,
            parent_lineage=(
                SimilarityParentLineage(
                    artifact_id=f"candidate-build:{pool.build_manifest_sha256}",
                    manifest_sha256=pool.build_manifest_sha256,
                    generation_git_commit=pool.build_manifest.git_commit,
                    generation_git_dirty=pool.build_manifest.git_dirty,
                ),
            ),
            candidate_dataset_sha256=pool.dataset_sha256,
            build_manifest_sha256=pool.build_manifest_sha256,
            fasta_sha256=pool.fasta_sha256,
            command=CandidateDiscoveryCommand(
                sanitized_argv=run_result.sanitized_argv,
                mmseqs_version=run_result.mmseqs_version,
                max_seqs=len(nodes),
                fixed_parameters=_fixed_parameters(config),
            ),
            counts=counts,
            artifacts=CandidateDiscoveryArtifactDigests(
                pair_table=SimilarityArtifactDigest(
                    logical_path=pair_table_logical_path,
                    row_count=len(edges),
                    file_sha256=row_artifacts.pair_table_sha256,
                    semantic_sha256=row_artifacts.pair_table_semantic_sha256,
                ),
                component_manifest=SimilarityArtifactDigest(
                    logical_path=component_manifest_logical_path,
                    row_count=len(partition.rows),
                    file_sha256=row_artifacts.component_manifest_sha256,
                    semantic_sha256=row_artifacts.component_manifest_semantic_sha256,
                ),
            ),
            software_version=__version__,
            generation_git_commit=generation_git.commit,
            generation_git_dirty=generation_git.dirty,
            python_version=platform.python_version(),
            uv_lock_sha256=uv_lock_sha256,
            release_eligible=config.run_mode == "freeze",
            ineligibility_reasons=ineligibility_reasons,
        )
        content_manifest_bytes = serialize_canonical_json(
            content_manifest.model_dump(mode="python")
        )
        content_manifest_sha256 = sha256_bytes(content_manifest_bytes)

        failure_stage = "staging_cleanup"
        if not _reset_staging(run.staging_dir, retain=False):
            raise DiscoveryError("unable to clean candidate discovery staging data")
        ended_at = _timestamp_utc(now())
        run_provenance = CandidateDiscoveryRunProvenance(
            started_at_utc=started_at,
            ended_at_utc=ended_at,
            resolved_executable=str(run_result.resolved_executable),
            staging_dir=str(run_result.staging_dir),
            architecture=platform.machine(),
            logical_cpu_count=os.cpu_count(),
            configured_threads=config.runtime.threads,
            sanitized_argv=run_result.sanitized_argv,
            returncode=run_result.returncode,
            timed_out=False,
            stderr_tail=run_result.stderr_tail,
            staged_file_sha256={
                "raw_pairs.tsv": raw_pair_tsv_sha256,
                "pair_table": row_artifacts.pair_table_sha256,
                "component_manifest": row_artifacts.component_manifest_sha256,
                "content_manifest": content_manifest_sha256,
            },
            cleanup_succeeded=True,
        )
        run_provenance_bytes = serialize_json_model(run_provenance)
        failure_stage = "artifact_publication"
        try:
            published = publish_bundle(
                {
                    config.output.pair_table: row_artifacts.pair_table_bytes,
                    config.output.component_manifest: row_artifacts.component_manifest_bytes,
                    config.output.content_manifest: content_manifest_bytes,
                    run_provenance_path: run_provenance_bytes,
                }
            )
        except PublicationError as error:
            raise DiscoveryError("candidate discovery artifact publication failed") from error
    except DiscoveryError as error:
        _record_failure_best_effort(
            error=error,
            failure_stage=failure_stage,
            run=run,
            run_result=run_result,
            started_at_utc=started_at,
            now=now,
            configured_threads=config.runtime.threads,
        )
        raise
    except OSError as error:
        discovery_error = DiscoveryError("candidate discovery local I/O failed")
        _record_failure_best_effort(
            error=discovery_error,
            failure_stage=failure_stage,
            run=run,
            run_result=run_result,
            started_at_utc=started_at,
            now=now,
            configured_threads=config.runtime.threads,
        )
        raise discovery_error from error

    return SimilarityArtifacts(
        pair_table_path=published[0],
        component_manifest_path=published[1],
        content_manifest_path=published[2],
        run_provenance_path=published[3],
        published_paths=published,
        content_manifest=content_manifest,
        sequence_count=counts.sequence_count,
        edge_count=counts.edge_count,
        component_count=counts.component_count,
        singleton_count=counts.singleton_count,
        largest_component_size=counts.largest_component_size,
    )


__all__ = [
    "COMPONENT_MANIFEST_SCHEMA",
    "PAIR_TABLE_SCHEMA",
    "DiscoveryError",
    "DiscoveryRunContextFactory",
    "SerializedDiscoveryRows",
    "SimilarityArtifacts",
    "create_discovery_run_context",
    "discover_candidate_pool",
    "serialize_discovery_rows",
]
