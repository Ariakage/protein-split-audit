# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from protein_split_audit.config import SimilarityConfigDocument, load_similarity_config_document
from protein_split_audit.data.build_candidates import CANDIDATE_SCHEMA
from protein_split_audit.provenance import (
    BuildCounts,
    BuildManifest,
    GitMetadata,
    serialize_json_model,
    sha256_bytes,
)
from protein_split_audit.similarity.connected_components import ComponentPartition, build_components
from protein_split_audit.similarity.mmseqs import MmseqsRunContext, MmseqsTool
from protein_split_audit.similarity.parse_clusters import SequenceNode, SimilarityEdge
from protein_split_audit.similarity.schemas import MmseqsRuntimeConfig


def test_discovery_row_schemas_are_explicit_and_nonnullable() -> None:
    from protein_split_audit.similarity.discovery import (
        COMPONENT_MANIFEST_SCHEMA,
        PAIR_TABLE_SCHEMA,
    )

    assert (
        pa.schema(
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
        == PAIR_TABLE_SCHEMA
    )
    assert (
        pa.schema(
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
        == COMPONENT_MANIFEST_SCHEMA
    )


def _semantic_lines(rows: list[list[object]]) -> bytes:
    return (
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    ).encode("utf-8")


def _valid_row_graph() -> tuple[
    SequenceNode,
    SequenceNode,
    SimilarityEdge,
    ComponentPartition,
]:
    first = SequenceNode(accession="FIRST", sequence_sha256="a" * 64)
    second = SequenceNode(accession="SECOND", sequence_sha256="b" * 64)
    edge = SimilarityEdge(
        left=first,
        right=second,
        query_accession=first.accession,
        target_accession=second.accession,
        fident=Decimal("0.40"),
        qcov=Decimal("0.80"),
        tcov=Decimal("0.80"),
        evalue=Decimal("0.001"),
        bits=Decimal("42"),
    )
    return first, second, edge, build_components((first, second), (edge,), Decimal("0.30"))


def test_serialize_discovery_rows_rejects_edge_endpoint_outside_partition() -> None:
    from protein_split_audit.similarity.discovery import (
        DiscoveryError,
        serialize_discovery_rows,
    )

    first, _second, edge, partition = _valid_row_graph()
    outsider = SequenceNode(accession="OUTSIDER", sequence_sha256="c" * 64)
    invalid = replace(
        edge,
        left=first,
        right=outsider,
        target_accession=outsider.accession,
    )

    with pytest.raises(DiscoveryError, match="partition"):
        serialize_discovery_rows(
            (invalid,),
            partition,
            ec_level_2_by_accession={"FIRST": "1.1", "SECOND": "2.7"},
            mmseqs_version="18-8cc5c",
        )


def test_serialize_discovery_rows_rejects_duplicate_undirected_edge() -> None:
    from protein_split_audit.similarity.discovery import (
        DiscoveryError,
        serialize_discovery_rows,
    )

    _first, _second, edge, partition = _valid_row_graph()
    duplicate = replace(
        edge,
        query_accession=edge.target_accession,
        target_accession=edge.query_accession,
    )

    with pytest.raises(DiscoveryError, match="duplicate"):
        serialize_discovery_rows(
            (edge, duplicate),
            partition,
            ec_level_2_by_accession={"FIRST": "1.1", "SECOND": "2.7"},
            mmseqs_version="18-8cc5c",
        )


def test_serialize_discovery_rows_rejects_observation_not_matching_endpoints() -> None:
    from protein_split_audit.similarity.discovery import (
        DiscoveryError,
        serialize_discovery_rows,
    )

    _first, _second, edge, partition = _valid_row_graph()
    invalid = replace(edge, target_accession="OUTSIDER")

    with pytest.raises(DiscoveryError, match="query/target"):
        serialize_discovery_rows(
            (invalid,),
            partition,
            ec_level_2_by_accession={"FIRST": "1.1", "SECOND": "2.7"},
            mmseqs_version="18-8cc5c",
        )


def test_serialize_discovery_rows_rejects_nonfinite_float_conversion() -> None:
    from protein_split_audit.similarity.discovery import (
        DiscoveryError,
        serialize_discovery_rows,
    )

    _first, _second, edge, partition = _valid_row_graph()
    overflow = replace(edge, bits=Decimal("1e10000"))

    with pytest.raises(DiscoveryError, match="finite float"):
        serialize_discovery_rows(
            (overflow,),
            partition,
            ec_level_2_by_accession={"FIRST": "1.1", "SECOND": "2.7"},
            mmseqs_version="18-8cc5c",
        )


def _write_candidate_inputs(
    tmp_path: Path,
    *,
    empty: bool = False,
    parent_git_commit: str | None = "5" * 40,
    parent_git_dirty: bool | None = False,
) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    row_specs = (
        ()
        if empty
        else (
            ("A00001", "FIRST_TEST", "A" * 50, "2.7.1.1"),
            ("B00002", "SECOND_TEST", "C" * 60, "1.1.1.1"),
        )
    )
    for index, (accession, entry_name, sequence, ec_number) in enumerate(row_specs, start=1):
        rows.append(
            {
                "primary_accession": accession,
                "entry_name": entry_name,
                "protein_name": f"Synthetic enzyme {index}",
                "organism_name": "Synthetic organism",
                "organism_id": 83333,
                "sequence": sequence,
                "sequence_length": len(sequence),
                "sequence_sha256": sha256_bytes(sequence.encode("ascii")),
                "ec_number": ec_number,
                "ec_level_2": ".".join(ec_number.split(".")[:2]),
                "duplicate_count": 1,
                "duplicate_accessions": [accession],
                "source_page_number": 1,
                "source_row_number": index,
            }
        )

    dataset = tmp_path / "candidate.parquet"
    fasta = tmp_path / "candidate.fasta"
    build_manifest = tmp_path / "candidate.build.json"
    pq.write_table(pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA), dataset)
    fasta_lines: list[str] = []
    for row in rows:
        fasta_lines.extend(
            (
                f">sp|{row['primary_accession']}|{row['entry_name']} "
                f"ec={row['ec_number']} taxon={row['organism_id']} "
                f"seq_sha256={row['sequence_sha256']}",
                str(row["sequence"]),
            )
        )
    if fasta_lines:
        fasta.write_text("\n".join(fasta_lines) + "\n", encoding="ascii", newline="\n")
    else:
        fasta.write_bytes(b"")
    manifest = BuildManifest(
        built_at_utc=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        parent_download_manifest="data/manifests/source.download.json",
        source_manifest_sha256="1" * 64,
        configuration_file="configs/data/source.yaml",
        configuration_sha256="2" * 64,
        input_file="data/raw/source.tsv.gz",
        input_file_sha256="3" * 64,
        input_normalized_content_sha256="4" * 64,
        output_file_sha256={
            dataset.name: sha256_bytes(dataset.read_bytes()),
            fasta.name: sha256_bytes(fasta.read_bytes()),
        },
        counts=BuildCounts(
            input_records=len(rows),
            after_ec_filter=len(rows),
            after_sequence_filter=len(rows),
            after_conflict_filter=len(rows),
            retained_candidates=len(rows),
        ),
        rejection_reason_counts={},
        duplicate_group_count=0,
        duplicate_alias_count=0,
        conflict_group_count=0,
        conflicting_record_count=0,
        processing_rules={},
        parquet_writer={},
        software_version="0.1.0",
        git_commit=parent_git_commit,
        git_dirty=parent_git_dirty,
        python_version="3.12.0",
        uv_lock_sha256="6" * 64,
    )
    build_manifest.write_bytes(serialize_json_model(manifest))
    return dataset, build_manifest, fasta


def test_serialize_discovery_rows_is_sorted_deterministic_and_semantically_hashed() -> None:
    from protein_split_audit.similarity.discovery import (
        COMPONENT_MANIFEST_SCHEMA,
        PAIR_TABLE_SCHEMA,
        serialize_discovery_rows,
    )

    first = SequenceNode(accession="ZETA", sequence_sha256="a" * 64)
    second = SequenceNode(accession="ALPHA", sequence_sha256="b" * 64)
    edge = SimilarityEdge(
        left=first,
        right=second,
        query_accession="ZETA",
        target_accession="ALPHA",
        fident=Decimal("0.4"),
        qcov=Decimal("0.80"),
        tcov=Decimal("0.900000"),
        evalue=Decimal("1e-3"),
        bits=Decimal("42.0"),
    )
    partition = build_components((second, first), (edge,), Decimal("0.30"))

    artifacts = serialize_discovery_rows(
        (edge,),
        partition,
        ec_level_2_by_accession={"ZETA": "3.1", "ALPHA": "2.7"},
        mmseqs_version="18-8cc5c",
    )
    repeated = serialize_discovery_rows(
        tuple(reversed((edge,))),
        partition,
        ec_level_2_by_accession={"ALPHA": "2.7", "ZETA": "3.1"},
        mmseqs_version="18-8cc5c",
    )

    assert artifacts == repeated
    assert artifacts.pair_table_sha256 == sha256_bytes(artifacts.pair_table_bytes)
    assert artifacts.component_manifest_sha256 == sha256_bytes(artifacts.component_manifest_bytes)
    pair_table = pq.read_table(pa.BufferReader(artifacts.pair_table_bytes))
    component_table = pq.read_table(pa.BufferReader(artifacts.component_manifest_bytes))
    assert pair_table.schema == PAIR_TABLE_SCHEMA
    assert component_table.schema == COMPONENT_MANIFEST_SCHEMA
    assert pair_table.column("left_sequence_sha256").to_pylist() == [bytes.fromhex("a" * 64)]
    assert component_table.column("accession").to_pylist() == ["ALPHA", "ZETA"]

    component_id = partition.rows[0].component_id
    assert artifacts.pair_table_semantic_sha256 == sha256_bytes(
        _semantic_lines(
            [
                [
                    "a" * 64,
                    "b" * 64,
                    "ZETA",
                    "ALPHA",
                    "0.400000",
                    "0.800000",
                    "0.900000",
                    "0.001",
                    "42",
                ]
            ]
        )
    )
    assert artifacts.component_manifest_semantic_sha256 == sha256_bytes(
        _semantic_lines(
            [
                [
                    "ALPHA",
                    "b" * 64,
                    "2.7",
                    component_id,
                    "ALPHA",
                    2,
                    "0.30",
                    "0.80",
                    "18-8cc5c",
                ],
                [
                    "ZETA",
                    "a" * 64,
                    "3.1",
                    component_id,
                    "ALPHA",
                    2,
                    "0.30",
                    "0.80",
                    "18-8cc5c",
                ],
            ]
        )
    )


def test_serialize_discovery_rows_is_byte_stable_under_edge_reordering() -> None:
    from protein_split_audit.similarity.discovery import serialize_discovery_rows

    first, second, first_edge, _partition = _valid_row_graph()
    third = SequenceNode(accession="THIRD", sequence_sha256="c" * 64)
    second_edge = SimilarityEdge(
        left=second,
        right=third,
        query_accession=third.accession,
        target_accession=second.accession,
        fident=Decimal("0.50"),
        qcov=Decimal("0.90"),
        tcov=Decimal("0.85"),
        evalue=Decimal("0.0001"),
        bits=Decimal("50"),
    )
    partition = build_components(
        (third, first, second),
        (second_edge, first_edge),
        Decimal("0.30"),
    )
    labels = {"FIRST": "1.1", "SECOND": "2.7", "THIRD": "3.1"}

    first_order = serialize_discovery_rows(
        (first_edge, second_edge),
        partition,
        ec_level_2_by_accession=labels,
        mmseqs_version="18-8cc5c",
    )
    reversed_order = serialize_discovery_rows(
        (second_edge, first_edge),
        partition,
        ec_level_2_by_accession=labels,
        mmseqs_version="18-8cc5c",
    )

    assert first_order == reversed_order


def _write_discovery_document(
    tmp_path: Path,
    *,
    run_mode: str = "development",
    empty: bool = False,
    parent_git_commit: str | None = "5" * 40,
    parent_git_dirty: bool | None = False,
) -> SimilarityConfigDocument:
    dataset, build_manifest, fasta = _write_candidate_inputs(
        tmp_path / "inputs",
        empty=empty,
        parent_git_commit=parent_git_commit,
        parent_git_dirty=parent_git_dirty,
    )
    mapping: dict[str, object] = {
        "schema_version": 1,
        "operation": "candidate_discovery",
        "name": "candidate-pool-cluster30",
        "run_mode": run_mode,
        "runtime": {
            "executable": "mmseqs",
            "cache_root": "../cache/mmseqs",
            "timeout_seconds": 5.0,
            "threads": 2,
        },
        "self_search": {
            "sensitivity": 7.5,
            "evalue": 0.001,
            "search_type": 1,
            "sequence_identity_mode": 0,
            "min_sequence_identity": 0.30,
            "minimum_coverage": 0.80,
            "coverage_mode": 0,
            "alignment_mode": 3,
            "format_mode": 4,
        },
        "input": {
            "candidate_dataset": "../inputs/candidate.parquet",
            "build_manifest": "../inputs/candidate.build.json",
            "fasta": "../inputs/candidate.fasta",
        },
        "output": {
            "component_manifest": "../outputs/components.parquet",
            "content_manifest": "../outputs/content.json",
            "pair_table": "../outputs/pairs.parquet",
            "run_dir": "../runs/discovery",
            "overwrite": False,
        },
    }
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "candidate-discovery.yaml"
    config_path.write_text(
        yaml.safe_dump(mapping, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    assert dataset == tmp_path / "inputs/candidate.parquet"
    assert build_manifest == tmp_path / "inputs/candidate.build.json"
    assert fasta == tmp_path / "inputs/candidate.fasta"
    return load_similarity_config_document(config_path)


class _DiscoveryProbe:
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self.calls: list[tuple[str, float]] = []

    def __call__(self, executable: str, *, timeout_seconds: float) -> MmseqsTool:
        self.calls.append((executable, timeout_seconds))
        return MmseqsTool(executable=self.executable, version="18-8cc5c")


class _DiscoveryExecutor:
    def __init__(self) -> None:
        self.argv: tuple[str, ...] | None = None
        self.kwargs: dict[str, Any] = {}

    def __call__(
        self,
        argv: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.argv = tuple(argv)
        self.kwargs = kwargs
        Path(argv[4]).write_text(
            "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits\n"
            "A00001\tA00001\t1.0\t1.0\t1.0\t0\t100\n"
            "B00002\tB00002\t1.0\t1.0\t1.0\t0\t100\n"
            "A00001\tB00002\t0.4\t0.9\t0.9\t1e-5\t80\n",
            encoding="utf-8",
            newline="\n",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="synthetic warning\n")


class _FailingDiscoveryExecutor:
    def __call__(
        self,
        argv: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            7,
            stdout="",
            stderr="visible detail\nAuthorization: Bearer top-secret\n",
        )


class _UnsafeSymlinkExecutor:
    def __init__(self, target: Path) -> None:
        self.target = target

    def __call__(
        self,
        argv: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        Path(argv[4]).symlink_to(self.target)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class _LowIdentityExecutor:
    def __call__(
        self,
        argv: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        Path(argv[4]).write_text(
            "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits\n"
            "A00001\tA00001\t1.0\t1.0\t1.0\t0\t100\n"
            "B00002\tB00002\t1.0\t1.0\t1.0\t0\t100\n"
            "A00001\tB00002\t0.29\t0.9\t0.9\t1e-5\t80\n",
            encoding="utf-8",
            newline="\n",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class _UnexpectedDiscoveryExecutor:
    def __init__(self) -> None:
        self.called = False

    def __call__(
        self,
        argv: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.called = True
        raise AssertionError(f"executor should not be called: {argv!r}")


class _MutatingFastaExecutor(_DiscoveryExecutor):
    def __call__(
        self,
        argv: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        completed = super().__call__(argv, **kwargs)
        fasta = Path(argv[2])
        fasta.write_bytes(fasta.read_bytes() + b"tampered\n")
        return completed


class _DiscoveryContextFactory:
    def __init__(self, tmp_path: Path, *, executor: Any | None = None) -> None:
        self.probe = _DiscoveryProbe((tmp_path / "bin/mmseqs").resolve())
        self.executor = _DiscoveryExecutor() if executor is None else executor
        self.runtime: MmseqsRuntimeConfig | None = None
        self.expected_output_name: str | None = None
        self.completed_outputs: tuple[Path, ...] = ()
        self.context: MmseqsRunContext | None = None

    def __call__(
        self,
        *,
        runtime: MmseqsRuntimeConfig,
        expected_output_name: str,
        completed_outputs: Sequence[Path],
    ) -> MmseqsRunContext:
        self.runtime = runtime
        self.expected_output_name = expected_output_name
        self.completed_outputs = tuple(completed_outputs)
        self.context = MmseqsRunContext.create(
            cache_root=runtime.cache_root,
            timeout_seconds=runtime.timeout_seconds,
            expected_output_names=(expected_output_name,),
            completed_outputs=completed_outputs,
            probe=self.probe,
            executor=self.executor,
        )
        return self.context


class _MutatingContextFactory(_DiscoveryContextFactory):
    def __init__(self, tmp_path: Path, fasta: Path) -> None:
        self.unexpected_executor = _UnexpectedDiscoveryExecutor()
        super().__init__(tmp_path, executor=self.unexpected_executor)
        self.fasta = fasta

    def __call__(
        self,
        *,
        runtime: MmseqsRuntimeConfig,
        expected_output_name: str,
        completed_outputs: Sequence[Path],
    ) -> MmseqsRunContext:
        context = super().__call__(
            runtime=runtime,
            expected_output_name=expected_output_name,
            completed_outputs=completed_outputs,
        )
        self.fasta.write_bytes(self.fasta.read_bytes() + b"tampered\n")
        return context


def test_discover_candidate_pool_runs_injected_pipeline_and_publishes_artifacts(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 2, 3, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 2, 4, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    result = discover_candidate_pool(
        document,
        run_context_factory=factory,
        now=lambda: next(timestamps),
        project_root=tmp_path,
    )

    assert result.sequence_count == 2
    assert result.edge_count == 1
    assert result.component_count == 1
    assert result.singleton_count == 0
    assert result.largest_component_size == 2
    assert result.published_paths == (
        document.config.output.pair_table,
        document.config.output.component_manifest,
        document.config.output.content_manifest,
        document.config.output.run_dir / "provenance.run.json",
    )
    assert all(path.is_file() for path in result.published_paths)
    assert factory.expected_output_name == "pairs.tsv"
    assert factory.executor.argv is not None
    argv = factory.executor.argv
    assert argv[2] == argv[3] == str(document.config.input.fasta)
    assert argv[argv.index("--max-seqs") + 1] == "2"
    assert factory.context is not None
    assert not factory.context.staging_dir.exists()

    content_bytes = document.config.output.content_manifest.read_bytes()
    content = json.loads(content_bytes)
    serialized = content_bytes.decode("utf-8")
    assert content_bytes.endswith(b"\n")
    assert b"\n" not in content_bytes[:-1]
    assert content["counts"] == {
        "component_count": 1,
        "edge_count": 1,
        "largest_component_size": 2,
        "per_class_component_counts": {"1.1": 1, "2.7": 1},
        "sequence_count": 2,
        "singleton_count": 0,
    }
    assert content["command"]["max_seqs"] == 2
    assert content["configuration_file"] == "configs/candidate-discovery.yaml"
    assert content["artifacts"]["pair_table"]["logical_path"] == "outputs/pairs.parquet"
    assert (
        content["artifacts"]["component_manifest"]["logical_path"] == "outputs/components.parquet"
    )
    assert content["release_eligible"] is False
    assert content["ineligibility_reasons"] == ["development_run_mode"]
    assert "2026-07-15" not in serialized
    assert str(tmp_path) not in serialized
    assert "A00001" not in serialized
    assert "B00002" not in serialized
    for sequence_hash in (
        pq.read_table(document.config.input.candidate_dataset).column("sequence_sha256").to_pylist()
    ):
        assert isinstance(sequence_hash, str)
        assert sequence_hash not in serialized

    run_provenance = json.loads(result.run_provenance_path.read_bytes())
    assert run_provenance["started_at_utc"] == "2026-07-15T01:02:03Z"
    assert run_provenance["ended_at_utc"] == "2026-07-15T01:02:04Z"
    assert run_provenance["cleanup_succeeded"] is True
    assert run_provenance["returncode"] == 0
    assert run_provenance["staging_dir"] == str(factory.context.staging_dir)


def test_mmseqs_failure_retains_redacted_provenance_and_does_not_block_retry(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    failed_factory = _DiscoveryContextFactory(
        tmp_path,
        executor=_FailingDiscoveryExecutor(),
    )
    timestamps = iter(datetime(2026, 7, 15, 1, 2, second, tzinfo=UTC) for second in (1, 2, 3, 4))
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="execution failed"):
        discover_candidate_pool(
            document,
            run_context_factory=failed_factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert failed_factory.context is not None
    failed_stage = failed_factory.context.staging_dir
    failure_path = failed_stage / "provenance.failure.json"
    assert {path.name for path in failed_stage.iterdir()} == {failure_path.name}
    failure_bytes = failure_path.read_bytes()
    failure = json.loads(failure_bytes)
    assert failure["outcome"] == "failure"
    assert failure["failure_stage"] == "mmseqs_execution"
    assert failure["returncode"] == 7
    assert failure["cleanup_succeeded"] is True
    assert failure["started_at_utc"] == "2026-07-15T01:02:01Z"
    assert failure["ended_at_utc"] == "2026-07-15T01:02:02Z"
    assert "top-secret" not in failure_bytes.decode("utf-8")
    assert "<redacted>" in failure["stderr_tail"]
    assert all(not path.exists() for path in failed_factory.completed_outputs)

    successful_factory = _DiscoveryContextFactory(tmp_path)
    result = discover_candidate_pool(
        document,
        run_context_factory=successful_factory,
        now=lambda: next(timestamps),
        project_root=tmp_path,
    )

    assert all(path.is_file() for path in result.published_paths)
    assert failure_path.is_file()
    assert successful_factory.context is not None
    assert not successful_factory.context.staging_dir.exists()


def test_dangerous_mmseqs_output_is_rejected_without_touching_target(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    outside = tmp_path / "outside.tsv"
    outside.write_bytes(b"do not modify\n")
    factory = _DiscoveryContextFactory(
        tmp_path,
        executor=_UnsafeSymlinkExecutor(outside),
    )
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 3, 1, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 3, 2, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="execution failed"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert outside.read_bytes() == b"do not modify\n"
    assert factory.context is not None
    assert {path.name for path in factory.context.staging_dir.iterdir()} == {
        "provenance.failure.json"
    }
    assert all(not path.exists() for path in factory.completed_outputs)


def test_discovery_rejects_pair_below_fixed_base_identity_predicate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path, executor=_LowIdentityExecutor())
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 4, 1, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 4, 2, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="identity predicate"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert factory.context is not None
    failure = json.loads((factory.context.staging_dir / "provenance.failure.json").read_bytes())
    assert failure["failure_stage"] == "pair_validation"
    assert all(not path.exists() for path in factory.completed_outputs)


def test_failure_provenance_write_error_does_not_mask_execution_error(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path, executor=_FailingDiscoveryExecutor())
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 5, 1, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 5, 2, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    def fail_to_write(_staging_dir: Path, _content: bytes) -> None:
        raise OSError("synthetic provenance failure")

    monkeypatch.setattr(discovery_module, "_write_failure_provenance", fail_to_write)

    with pytest.raises(DiscoveryError, match="execution failed"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert factory.context is not None
    assert factory.context.staging_dir.is_dir()
    assert list(factory.context.staging_dir.iterdir()) == []
    assert all(not path.exists() for path in factory.completed_outputs)


def test_discovery_reconciles_fasta_hash_immediately_before_execution(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _MutatingContextFactory(tmp_path, document.config.input.fasta)
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 6, 1, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 6, 2, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="input changed during discovery"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert factory.unexpected_executor.called is False
    assert factory.context is not None
    failure = json.loads((factory.context.staging_dir / "provenance.failure.json").read_bytes())
    assert failure["failure_stage"] == "input_reconciliation"
    assert all(not path.exists() for path in factory.completed_outputs)


def test_discovery_reconciles_fasta_hash_after_execution_before_publication(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path, executor=_MutatingFastaExecutor())
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 7, 2, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="input changed during discovery"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert factory.context is not None
    failure = json.loads((factory.context.staging_dir / "provenance.failure.json").read_bytes())
    assert failure["failure_stage"] == "input_reconciliation"
    assert failure["returncode"] == 0
    assert all(not path.exists() for path in factory.completed_outputs)


def test_publication_failure_publishes_nothing_and_retains_failure_provenance(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.publication import PublicationError
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    timestamps = iter(
        (
            datetime(2026, 7, 15, 1, 8, 1, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 8, 2, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    def fail_publication(_outputs: dict[Path, bytes]) -> tuple[Path, ...]:
        raise PublicationError("synthetic publication failure")

    monkeypatch.setattr(discovery_module, "publish_bundle", fail_publication)

    with pytest.raises(DiscoveryError, match="publication failed"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            now=lambda: next(timestamps),
            project_root=tmp_path,
        )

    assert factory.context is not None
    failure_path = factory.context.staging_dir / "provenance.failure.json"
    failure = json.loads(failure_path.read_bytes())
    assert failure["failure_stage"] == "artifact_publication"
    assert failure["returncode"] == 0
    assert all(not path.exists() for path in factory.completed_outputs)


def test_discovery_refuses_external_config_before_staging(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "uv.lock").write_bytes(b"synthetic lock\n")
    document = _write_discovery_document(tmp_path / "private-config")
    factory = _DiscoveryContextFactory(project_root)
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="project tree"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            project_root=project_root,
        )

    assert factory.context is None
    assert all(not path.exists() for path in factory.completed_outputs)


def test_discovery_refuses_external_publish_destination_before_staging(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    project_root = tmp_path / "project"
    document = _write_discovery_document(project_root)
    mapping = yaml.safe_load(document.source_bytes)
    assert isinstance(mapping, dict)
    mapping["output"] = {
        "component_manifest": "../../private-output/components.parquet",
        "content_manifest": "../../private-output/content.json",
        "pair_table": "../../private-output/pairs.parquet",
        "run_dir": "../../private-output/run",
        "overwrite": False,
    }
    document.source_path.write_text(
        yaml.safe_dump(mapping, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    document = load_similarity_config_document(document.source_path)
    (project_root / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(project_root)
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    with pytest.raises(DiscoveryError, match="project tree"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            project_root=project_root,
        )

    assert factory.context is None
    assert all(not path.exists() for path in factory.completed_outputs)


def test_existing_artifact_is_refused_before_staging(tmp_path: Path) -> None:
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path)
    existing = document.config.output.pair_table
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"sentinel\n")
    factory = _DiscoveryContextFactory(tmp_path)

    with pytest.raises(DiscoveryError, match="overwrite"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            project_root=tmp_path,
        )

    assert existing.read_bytes() == b"sentinel\n"
    assert factory.context is None


def test_empty_candidate_pool_is_refused_before_staging(tmp_path: Path) -> None:
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(tmp_path, empty=True)
    factory = _DiscoveryContextFactory(tmp_path)

    with pytest.raises(DiscoveryError, match="non-empty"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            project_root=tmp_path,
        )

    assert factory.context is None


def test_development_lineage_preserves_parent_and_orders_ineligibility_reasons(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import discover_candidate_pool

    document = _write_discovery_document(tmp_path, parent_git_dirty=True)
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=False, commit=None, dirty=None),
    )

    result = discover_candidate_pool(
        document,
        run_context_factory=factory,
        project_root=tmp_path,
    )

    content = result.content_manifest
    assert content.release_eligible is False
    assert content.ineligibility_reasons == (
        "development_run_mode",
        "parent_git_dirty",
        "generation_git_state_unknown",
    )
    assert len(content.parent_lineage) == 1
    assert content.parent_lineage[0].generation_git_commit == "5" * 40
    assert content.parent_lineage[0].generation_git_dirty is True


def test_development_lineage_lists_dirty_and_unknown_states_independently(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import discover_candidate_pool

    document = _write_discovery_document(
        tmp_path,
        parent_git_commit=None,
        parent_git_dirty=True,
    )
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=False, commit=None, dirty=True),
    )

    result = discover_candidate_pool(
        document,
        run_context_factory=factory,
        project_root=tmp_path,
    )

    assert result.content_manifest.ineligibility_reasons == (
        "development_run_mode",
        "parent_git_dirty",
        "parent_git_state_unknown",
        "generation_git_dirty",
        "generation_git_state_unknown",
    )


def test_clean_freeze_is_release_eligible_and_preserves_parent_lineage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import discover_candidate_pool

    document = _write_discovery_document(tmp_path, run_mode="freeze")
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )

    result = discover_candidate_pool(
        document,
        run_context_factory=factory,
        project_root=tmp_path,
    )

    content = result.content_manifest
    assert content.release_eligible is True
    assert content.ineligibility_reasons == ()
    assert content.parent_lineage[0].generation_git_commit == "5" * 40
    assert content.parent_lineage[0].generation_git_dirty is False


@pytest.mark.parametrize(
    ("parent_git_commit", "parent_git_dirty", "generation_git"),
    (
        (
            "5" * 40,
            True,
            GitMetadata(available=True, commit="7" * 40, dirty=False),
        ),
        (
            None,
            False,
            GitMetadata(available=True, commit="7" * 40, dirty=False),
        ),
        (
            "5" * 40,
            False,
            GitMetadata(available=True, commit="7" * 40, dirty=True),
        ),
        (
            "5" * 40,
            False,
            GitMetadata(available=False, commit=None, dirty=None),
        ),
    ),
    ids=(
        "parent-dirty",
        "parent-unknown",
        "generation-dirty",
        "generation-unknown",
    ),
)
def test_freeze_rejects_dirty_or_unknown_lineage_before_staging(
    tmp_path: Path,
    monkeypatch: Any,
    parent_git_commit: str | None,
    parent_git_dirty: bool | None,
    generation_git: GitMetadata,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(
        tmp_path,
        run_mode="freeze",
        parent_git_commit=parent_git_commit,
        parent_git_dirty=parent_git_dirty,
    )
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    monkeypatch.setattr(discovery_module, "git_metadata", lambda _root: generation_git)

    with pytest.raises(DiscoveryError, match="clean known Git lineage"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            project_root=tmp_path,
        )

    assert factory.context is None
    assert all(not path.exists() for path in factory.completed_outputs)


@pytest.mark.parametrize(
    ("run_mode", "parent_git_commit", "generation_git"),
    (
        (
            "development",
            "not-a-40-character-hex-commit",
            GitMetadata(available=True, commit="7" * 40, dirty=False),
        ),
        (
            "freeze",
            "",
            GitMetadata(available=True, commit="7" * 40, dirty=False),
        ),
        (
            "development",
            "5" * 40,
            GitMetadata(available=True, commit="not-hex", dirty=False),
        ),
        (
            "freeze",
            "5" * 40,
            GitMetadata(available=True, commit="A" * 40, dirty=False),
        ),
    ),
    ids=("dev-parent", "freeze-parent", "dev-generation", "freeze-generation"),
)
def test_discovery_rejects_invalid_git_commit_before_staging(
    tmp_path: Path,
    monkeypatch: Any,
    run_mode: str,
    parent_git_commit: str,
    generation_git: GitMetadata,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import DiscoveryError, discover_candidate_pool

    document = _write_discovery_document(
        tmp_path,
        run_mode=run_mode,
        parent_git_commit=parent_git_commit,
    )
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock\n")
    factory = _DiscoveryContextFactory(tmp_path)
    monkeypatch.setattr(discovery_module, "git_metadata", lambda _root: generation_git)

    with pytest.raises(DiscoveryError, match="invalid Git commit provenance"):
        discover_candidate_pool(
            document,
            run_context_factory=factory,
            project_root=tmp_path,
        )

    assert factory.context is None


def test_deterministic_artifacts_ignore_run_time_and_project_location(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import protein_split_audit.similarity.discovery as discovery_module
    from protein_split_audit.similarity.discovery import discover_candidate_pool

    roots = (tmp_path / "first", tmp_path / "second")
    documents = tuple(_write_discovery_document(root) for root in roots)
    for root in roots:
        (root / "uv.lock").write_bytes(b"synthetic lock\n")
    monkeypatch.setattr(
        discovery_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )
    clocks = (
        iter(
            (
                datetime(2026, 7, 15, 1, 1, 1, tzinfo=UTC),
                datetime(2026, 7, 15, 1, 1, 2, tzinfo=UTC),
            )
        ),
        iter(
            (
                datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC),
                datetime(2030, 1, 2, 3, 4, 6, tzinfo=UTC),
            )
        ),
    )

    results = tuple(
        discover_candidate_pool(
            document,
            run_context_factory=_DiscoveryContextFactory(root),
            now=lambda clock=clock: next(clock),
            project_root=root,
        )
        for root, document, clock in zip(roots, documents, clocks, strict=True)
    )

    for attribute in ("pair_table_path", "component_manifest_path", "content_manifest_path"):
        first_path = getattr(results[0], attribute)
        second_path = getattr(results[1], attribute)
        assert first_path.read_bytes() == second_path.read_bytes()
    assert (
        results[0].run_provenance_path.read_bytes() != results[1].run_provenance_path.read_bytes()
    )
