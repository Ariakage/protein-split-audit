# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import gzip
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from protein_split_audit import __version__
from protein_split_audit.config import BuildConfig
from protein_split_audit.data.build_candidates import BuildError, build_candidate_dataset
from protein_split_audit.provenance import (
    DownloadManifest,
    DownloadPageProvenance,
    serialize_download_manifest,
    sha256_bytes,
)

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parents[1]
FIXED_TIME = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)


def make_build_config(tmp_path: Path) -> tuple[BuildConfig, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "pilot.yaml"
    config_path.write_text("schema_version: 1\nrun_name: offline-pilot\n", encoding="utf-8")
    fields = [
        ("accession", "Entry"),
        ("id", "Entry Name"),
        ("protein_name", "Protein names"),
        ("organism_name", "Organism"),
        ("organism_id", "Organism (ID)"),
        ("ec", "EC number"),
        ("sequence", "Sequence"),
    ]
    config = BuildConfig.model_validate(
        {
            "schema_version": 1,
            "run_name": "offline-pilot",
            "source": {
                "database": "UniProtKB/Swiss-Prot",
                "endpoint": "https://rest.uniprot.org/uniprotkb/search",
                "query": "reviewed:true AND taxonomy_id:83333 AND fragment:false AND ec:*",
                "fields": [
                    {"name": name, "response_header": header, "required": True}
                    for name, header in fields
                ],
                "page_size": 100,
                "timeout_seconds": 5.0,
            },
            "retry": {
                "max_retries": 1,
                "backoff_initial_seconds": 0.1,
                "backoff_max_seconds": 0.2,
            },
            "output": {
                "raw_dir": tmp_path / "data/raw",
                "manifest_dir": tmp_path / "data/manifests",
                "compressed_filename": "offline-pilot.tsv.gz",
                "manifest_filename": "offline-pilot.download.json",
                "overwrite": False,
            },
            "candidate_selection": {
                "allowed_amino_acids": "ACDEFGHIKLMNPQRSTVWY",
                "min_sequence_length": 50,
                "max_sequence_length": 1000,
                "require_single_ec": True,
                "require_complete_ec": True,
            },
            "build_output": {
                "processed_dir": tmp_path / "data/processed",
                "manifest_dir": tmp_path / "data/manifests",
                "parquet_filename": "pilot.parquet",
                "fasta_filename": "pilot.fasta",
                "manifest_filename": "pilot.build.json",
                "deduplication_filename": "pilot.deduplication.json",
                "conflicts_filename": "pilot.conflicting-duplicates.json",
                "rejections_filename": "pilot.rejections.json",
                "overwrite": False,
            },
        }
    )
    return config, config_path


def prepare_source(config: BuildConfig, tmp_path: Path) -> bytes:
    source = (FIXTURES / "candidate_build.tsv").read_bytes()
    compressed = gzip.compress(source, compresslevel=9, mtime=0)
    source_path = config.output.raw_dir / config.output.compressed_filename
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(compressed)
    shutil.copy2(PROJECT_ROOT / "uv.lock", tmp_path / "uv.lock")

    records = len(source.decode().splitlines()) - 1
    manifest = DownloadManifest(
        source_database=config.source.database,
        endpoint=str(config.source.endpoint),
        query=config.source.query,
        canonical_request_url="https://rest.uniprot.org/uniprotkb/search?synthetic=true",
        requested_fields=config.source.requested_fields,
        downloaded_at_utc=FIXED_TIME,
        uniprot_release="synthetic-test-release",
        uniprot_release_date="2099-01-01",
        page_count=1,
        record_count=records,
        expected_total_count=records,
        normalized_content_sha256=sha256_bytes(source),
        local_compressed_file="data/raw/offline-pilot.tsv.gz",
        local_compressed_file_sha256=sha256_bytes(compressed),
        software_version=__version__,
        git_commit=None,
        git_dirty=True,
        python_version="3.12.0",
        uv_lock_sha256="0" * 64,
        pages=(
            DownloadPageProvenance(
                page_number=1,
                request_url="https://rest.uniprot.org/uniprotkb/search?synthetic=true",
                response_headers={"x-total-results": str(records)},
                record_count=records,
                normalized_page_sha256=sha256_bytes(source),
            ),
        ),
    )
    manifest_path = config.output.manifest_dir / config.output.manifest_filename
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(serialize_download_manifest(manifest))
    return source


def run_build(tmp_path: Path):
    config, config_path = make_build_config(tmp_path)
    source = prepare_source(config, tmp_path)
    result = build_candidate_dataset(
        config,
        config_path=config_path,
        project_root=tmp_path,
        now=lambda: FIXED_TIME,
    )
    return result, source


def test_fixture_build_deduplicates_and_rejects_conflicts(tmp_path: Path) -> None:
    result, _source = run_build(tmp_path)
    table = pq.read_table(result.parquet_path)
    dedup = json.loads(result.deduplication_path.read_text(encoding="utf-8"))
    conflicts = json.loads(result.conflicts_path.read_text(encoding="utf-8"))

    assert table.column("primary_accession").to_pylist() == ["A00001", "C00001"]
    assert table.column("ec_level_2").to_pylist() == ["2.7", "3.3"]
    assert table.column("duplicate_accessions").to_pylist()[0] == ["A00001", "A00002"]
    assert dedup["groups"][0]["canonical_accession"] == "A00001"
    assert dedup["groups"][0]["alias_accessions"] == ["A00002"]
    assert conflicts["conflict_group_count"] == 1
    assert conflicts["conflicting_record_count"] == 2
    assert conflicts["groups"][0]["labels"] == ["1.1", "2.2"]
    assert [member["accession"] for member in conflicts["groups"][0]["members"]] == [
        "B00001",
        "B00002",
    ]


def test_outputs_are_deterministic_and_parquet_has_declared_sorting(tmp_path: Path) -> None:
    first, _ = run_build(tmp_path / "first")
    second, _ = run_build(tmp_path / "second")

    assert first.fasta_path.read_bytes() == second.fasta_path.read_bytes()
    assert first.parquet_path.read_bytes() == second.parquet_path.read_bytes()
    fasta = first.fasta_path.read_text(encoding="ascii")
    assert fasta.startswith(">sp|A00001|DUP1_TEST ec=2.7.12.1 taxon=83333 seq_sha256=")
    assert fasta.endswith("\n")
    assert next(line for line in fasta.splitlines() if not line.startswith(">")) == "A" * 50

    table = pq.read_table(first.parquet_path)
    assert table.column_names == [
        "primary_accession",
        "entry_name",
        "protein_name",
        "organism_name",
        "organism_id",
        "sequence",
        "sequence_length",
        "sequence_sha256",
        "ec_number",
        "ec_level_2",
        "duplicate_count",
        "duplicate_accessions",
        "source_page_number",
        "source_row_number",
    ]
    assert table.column("primary_accession").to_pylist() == sorted(
        table.column("primary_accession").to_pylist()
    )


def test_manifest_and_aggregate_rejections_reconcile(tmp_path: Path) -> None:
    result, source = run_build(tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    rejections = json.loads(result.rejections_path.read_text(encoding="utf-8"))

    assert manifest["manifest_schema_version"] == 1
    assert manifest["source_manifest_sha256"]
    assert manifest["configuration_sha256"]
    assert manifest["input_file_sha256"]
    assert manifest["input_normalized_content_sha256"] == sha256_bytes(source)
    assert set(manifest["output_file_sha256"]) == {
        "pilot.conflicting-duplicates.json",
        "pilot.deduplication.json",
        "pilot.fasta",
        "pilot.parquet",
        "pilot.rejections.json",
    }
    assert manifest["counts"] == {
        "input_records": 9,
        "after_ec_filter": 6,
        "after_sequence_filter": 5,
        "after_conflict_filter": 3,
        "retained_candidates": 2,
    }
    assert manifest["rejection_reason_counts"] == {
        "incomplete_ec": 1,
        "invalid_sequence_characters": 1,
        "malformed_ec": 1,
        "multiple_ec": 1,
    }
    assert manifest["duplicate_group_count"] == 1
    assert manifest["duplicate_alias_count"] == 1
    assert manifest["conflict_group_count"] == 1
    assert manifest["conflicting_record_count"] == 2
    assert manifest["software_version"] == __version__
    assert "git_commit" in manifest
    assert manifest["git_dirty"] is None
    assert manifest["uv_lock_sha256"]
    assert rejections["reason_counts"] == manifest["rejection_reason_counts"]
    assert manifest["output_file_sha256"]["pilot.parquet"] == sha256_bytes(
        result.parquet_path.read_bytes()
    )
    assert manifest["output_file_sha256"]["pilot.fasta"] == sha256_bytes(
        result.fasta_path.read_bytes()
    )
    for path in (
        result.manifest_path,
        result.deduplication_path,
        result.conflicts_path,
        result.rejections_path,
    ):
        assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in path.read_text(
            encoding="utf-8"
        )


def test_build_refuses_to_overwrite_any_artifact(tmp_path: Path) -> None:
    config, config_path = make_build_config(tmp_path)
    prepare_source(config, tmp_path)
    build_candidate_dataset(
        config,
        config_path=config_path,
        project_root=tmp_path,
        now=lambda: FIXED_TIME,
    )

    with pytest.raises(BuildError, match="refusing to overwrite"):
        build_candidate_dataset(
            config,
            config_path=config_path,
            project_root=tmp_path,
            now=lambda: FIXED_TIME,
        )
