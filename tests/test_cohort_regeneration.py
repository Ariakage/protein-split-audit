# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from protein_split_audit.data.build_candidates import CANDIDATE_SCHEMA, PARQUET_WRITER_SETTINGS
from protein_split_audit.provenance import (
    BuildCounts,
    BuildManifest,
    DownloadManifest,
    DownloadPageProvenance,
    GitMetadata,
    serialize_download_manifest,
    serialize_json_model,
    sha256_bytes,
)


def _candidate_row(
    accession: str,
    label: str,
    sequence: str,
    *,
    source_row: int,
) -> dict[str, Any]:
    return {
        "primary_accession": accession,
        "entry_name": f"{accession}_TEST",
        "protein_name": f"Synthetic {accession}",
        "organism_name": "Synthetic organism",
        "organism_id": 83333,
        "sequence": sequence,
        "sequence_length": len(sequence),
        "sequence_sha256": sha256_bytes(sequence.encode("ascii")),
        "ec_number": f"{label}.1.1",
        "ec_level_2": label,
        "duplicate_count": 1,
        "duplicate_accessions": [accession],
        "source_page_number": 1,
        "source_row_number": source_row,
    }


def _fasta_bytes(rows: list[dict[str, Any]]) -> bytes:
    lines: list[str] = []
    for row in rows:
        lines.extend(
            (
                f">sp|{row['primary_accession']}|{row['entry_name']} "
                f"ec={row['ec_number']} taxon={row['organism_id']} "
                f"seq_sha256={row['sequence_sha256']}",
                str(row["sequence"]),
            )
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def _write_lineage(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    commit: str = "a" * 40,
    dirty: bool = False,
    lock_hash: str = "b" * 64,
    release: str | None = "2026_02",
    downloaded_at: datetime = datetime(2026, 7, 15, tzinfo=UTC),
) -> object:
    from protein_split_audit.cohort.regeneration import CandidateLineagePaths

    root.mkdir(parents=True)
    raw = root / "source.tsv.gz"
    download_path = root / "source.download.json"
    dataset = root / "pilot.parquet"
    fasta = root / "pilot.fasta"
    build_path = root / "pilot.build.json"

    source_lines = ["Entry\tEC number\tSequence"]
    source_lines.extend(
        f"{row['primary_accession']}\t{row['ec_number']}\t{row['sequence']}" for row in rows
    )
    normalized_source = ("\n".join(source_lines) + "\n").encode("utf-8")
    compressed = gzip.compress(normalized_source, compresslevel=9, mtime=0)
    raw.write_bytes(compressed)
    request_url = "https://rest.uniprot.org/uniprotkb/search?query=synthetic"
    download = DownloadManifest(
        source_database="UniProtKB/Swiss-Prot",
        endpoint="https://rest.uniprot.org/uniprotkb/search",
        query="reviewed:true AND taxonomy_id:83333 AND fragment:false AND ec:*",
        canonical_request_url=request_url,
        requested_fields=("accession", "ec", "sequence"),
        downloaded_at_utc=downloaded_at,
        uniprot_release=release,
        uniprot_release_date="10-June-2026" if release is not None else None,
        page_count=1,
        record_count=len(rows),
        expected_total_count=len(rows),
        normalized_content_sha256=sha256_bytes(normalized_source),
        local_compressed_file=raw.name,
        local_compressed_file_sha256=sha256_bytes(compressed),
        software_version="0.1.1",
        git_commit=commit,
        git_dirty=dirty,
        python_version="3.12.0",
        uv_lock_sha256=lock_hash,
        pages=(
            DownloadPageProvenance(
                page_number=1,
                request_url=request_url,
                response_headers={"x-uniprot-release": release or ""},
                record_count=len(rows),
                normalized_page_sha256=sha256_bytes(normalized_source),
            ),
        ),
    )
    download_path.write_bytes(serialize_download_manifest(download))

    table = pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA)
    pq.write_table(table, dataset, row_group_size=65_536, **PARQUET_WRITER_SETTINGS)
    fasta.write_bytes(_fasta_bytes(rows))
    build = BuildManifest(
        built_at_utc=downloaded_at,
        parent_download_manifest=download_path.name,
        source_manifest_sha256=sha256_bytes(download_path.read_bytes()),
        configuration_file="configs/dataset/pilot-clean-regeneration.yaml",
        configuration_sha256="c" * 64,
        input_file=raw.name,
        input_file_sha256=sha256_bytes(compressed),
        input_normalized_content_sha256=sha256_bytes(normalized_source),
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
        processing_rules={"deduplication": "exact-sequence-sha256-v1"},
        parquet_writer=PARQUET_WRITER_SETTINGS,
        software_version="0.1.1",
        git_commit=commit,
        git_dirty=dirty,
        python_version="3.12.0",
        uv_lock_sha256=lock_hash,
    )
    build_path.write_bytes(serialize_json_model(build))
    return CandidateLineagePaths(
        raw_download=raw,
        download_manifest=download_path,
        candidate_dataset=dataset,
        candidate_fasta=fasta,
        build_manifest=build_path,
    )


def _rows() -> list[dict[str, Any]]:
    return [
        _candidate_row("P00001", "1.1", "A" * 50, source_row=1),
        _candidate_row("P00002", "2.7", "C" * 50, source_row=2),
    ]


def test_load_candidate_lineage_reconciles_clean_source_build_and_candidates(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.regeneration import load_candidate_lineage

    lineage = load_candidate_lineage(
        _write_lineage(tmp_path / "clean", _rows()), require_clean=True
    )

    assert lineage.download_manifest.git_dirty is False
    assert lineage.build_manifest.git_commit == "a" * 40
    assert lineage.pool.records[0].accession == "P00001"
    assert lineage.normalized_source_sha256 == lineage.download_manifest.normalized_content_sha256
    assert lineage.uv_lock_sha256 == "b" * 64


@pytest.mark.parametrize(
    ("dirty", "commit", "lock_hash", "release", "message"),
    [
        (True, "a" * 40, "b" * 64, "2026_02", "clean"),
        (False, "short", "b" * 64, "2026_02", "commit"),
        (False, "a" * 40, "b" * 64, None, "release"),
    ],
)
def test_load_clean_lineage_rejects_ineligible_provenance(
    tmp_path: Path,
    dirty: bool,
    commit: str,
    lock_hash: str,
    release: str | None,
    message: str,
) -> None:
    from protein_split_audit.cohort.regeneration import RegenerationError, load_candidate_lineage

    paths = _write_lineage(
        tmp_path / message,
        _rows(),
        dirty=dirty,
        commit=commit,
        lock_hash=lock_hash,
        release=release,
    )

    with pytest.raises(RegenerationError, match=message):
        load_candidate_lineage(paths, require_clean=True)


def test_load_historical_lineage_preserves_dirty_state(tmp_path: Path) -> None:
    from protein_split_audit.cohort.regeneration import load_candidate_lineage

    lineage = load_candidate_lineage(
        _write_lineage(tmp_path / "historical", _rows(), dirty=True),
        require_clean=False,
    )

    assert lineage.download_manifest.git_dirty is True
    assert lineage.build_manifest.git_dirty is True


def test_compare_regeneration_is_deterministic_and_ignores_timestamps(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.regeneration import (
        compare_candidate_regeneration,
        load_candidate_lineage,
    )

    historical = load_candidate_lineage(
        _write_lineage(
            tmp_path / "old",
            _rows(),
            dirty=True,
            downloaded_at=datetime(2026, 7, 14, tzinfo=UTC),
        ),
        require_clean=False,
    )
    regenerated = load_candidate_lineage(
        _write_lineage(
            tmp_path / "new",
            _rows(),
            downloaded_at=datetime(2026, 7, 15, tzinfo=UTC),
        ),
        require_clean=True,
    )

    first = compare_candidate_regeneration(historical, regenerated)
    second = compare_candidate_regeneration(historical, regenerated)

    assert first == second
    assert first.aggregate_bytes == second.aggregate_bytes
    assert first.detail_parquet_bytes == second.detail_parquet_bytes
    assert first.report["comparison_rule_version"] == "candidate-regeneration-diff-v1"
    assert first.report["outcome"] == "byte_identical"
    assert first.report["historical_deduplication_map_used"] is False
    assert first.report["candidate_comparison"]["detail_row_count"] == 0
    assert b"downloaded_at" not in first.aggregate_bytes


def test_compare_regeneration_reports_changes_without_sequences_or_accessions_in_aggregate(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.regeneration import (
        compare_candidate_regeneration,
        load_candidate_lineage,
    )

    old_rows = _rows()
    new_rows = [
        _candidate_row("P00001", "1.1", "D" * 50, source_row=10),
        _candidate_row("P00003", "3.1", "E" * 50, source_row=20),
    ]
    historical = load_candidate_lineage(
        _write_lineage(tmp_path / "old-change", old_rows, dirty=True), require_clean=False
    )
    regenerated = load_candidate_lineage(
        _write_lineage(tmp_path / "new-change", new_rows), require_clean=True
    )

    difference = compare_candidate_regeneration(historical, regenerated)
    aggregate_text = difference.aggregate_bytes.decode("utf-8")

    assert difference.report["outcome"] == "source_or_candidate_content_changed_review_required"
    comparison = difference.report["candidate_comparison"]
    assert comparison["added_accession_count"] == 1
    assert comparison["removed_accession_count"] == 1
    assert comparison["changed_sequence_count"] == 1
    assert comparison["detail_row_count"] == 3
    assert "P00001" not in aggregate_text
    assert "P00002" not in aggregate_text
    assert "P00003" not in aggregate_text
    assert "A" * 50 not in aggregate_text
    assert "D" * 50 not in aggregate_text


def test_load_candidate_lineage_rejects_raw_hash_mismatch(tmp_path: Path) -> None:
    from protein_split_audit.cohort.regeneration import RegenerationError, load_candidate_lineage

    paths = _write_lineage(tmp_path / "tampered", _rows())
    paths.raw_download.write_bytes(b"tampered")

    with pytest.raises(RegenerationError, match="raw download hash"):
        load_candidate_lineage(paths, require_clean=True)


def test_write_regeneration_difference_publishes_bundle_without_overwrite(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.regeneration import (
        RegenerationError,
        compare_candidate_regeneration,
        load_candidate_lineage,
        load_regeneration_difference_report,
        write_regeneration_difference,
    )

    historical = load_candidate_lineage(
        _write_lineage(tmp_path / "write-old", _rows(), dirty=True), require_clean=False
    )
    regenerated = load_candidate_lineage(
        _write_lineage(tmp_path / "write-new", _rows()), require_clean=True
    )
    difference = compare_candidate_regeneration(historical, regenerated)
    output_dir = tmp_path / "review"

    paths = write_regeneration_difference(difference, output_dir)

    assert paths.aggregate.read_bytes() == difference.aggregate_bytes
    assert paths.detail.read_bytes() == difference.detail_parquet_bytes
    loaded = load_regeneration_difference_report(paths.aggregate)
    assert loaded.report == difference.report
    assert loaded.aggregate_sha256 == difference.aggregate_sha256
    with pytest.raises(RegenerationError, match="overwrite"):
        write_regeneration_difference(difference, output_dir)


def _freeze_inputs(tmp_path: Path) -> tuple[object, object, object, object, object]:
    from protein_split_audit.cohort.freeze import DiscoveryFreezeLineage, FreezeReview
    from protein_split_audit.cohort.regeneration import (
        compare_candidate_regeneration,
        load_candidate_lineage,
    )

    historical = load_candidate_lineage(
        _write_lineage(tmp_path / "freeze-old", _rows(), dirty=True), require_clean=False
    )
    regenerated = load_candidate_lineage(
        _write_lineage(tmp_path / "freeze-new", _rows()), require_clean=True
    )
    difference = compare_candidate_regeneration(historical, regenerated)
    discovery = DiscoveryFreezeLineage(
        content_manifest_sha256="d" * 64,
        candidate_dataset_sha256=regenerated.pool.dataset_sha256,
        build_manifest_sha256=regenerated.build_manifest_sha256,
        fasta_sha256=regenerated.pool.fasta_sha256,
        generation_git_commit="a" * 40,
        generation_git_dirty=False,
        uv_lock_sha256="b" * 64,
        release_eligible=True,
        ineligibility_reasons=(),
    )
    review = FreezeReview(
        decision="approved-for-pilot-v1-freeze",
        selection_rule_version="pilot-ec2-5class-min40-c30g10-cap250-seed42-v1",
        generation_git_commit="a" * 40,
        uv_lock_sha256="b" * 64,
        historical_download_manifest_sha256=historical.download_manifest_sha256,
        historical_build_manifest_sha256=historical.build_manifest_sha256,
        regenerated_download_manifest_sha256=regenerated.download_manifest_sha256,
        regenerated_build_manifest_sha256=regenerated.build_manifest_sha256,
        difference_report_sha256=difference.aggregate_sha256,
        discovery_content_manifest_sha256=discovery.content_manifest_sha256,
        approval_reference="maintainer-decision-task-5-2026-07-15",
    )
    return historical, regenerated, difference, discovery, review


def test_validate_freeze_review_binds_every_clean_input(tmp_path: Path) -> None:
    from protein_split_audit.cohort.freeze import validate_freeze_review

    historical, regenerated, difference, discovery, review = _freeze_inputs(tmp_path)

    evidence = validate_freeze_review(
        review,
        difference=difference,
        historical=historical,
        regenerated=regenerated,
        discovery=discovery,
        current_git=GitMetadata(available=True, commit="a" * 40, dirty=False),
        actual_uv_lock_sha256="b" * 64,
    )

    assert evidence.cohort_version == "pilot-v1"
    assert evidence.generation_git_commit == "a" * 40
    assert evidence.difference_report_sha256 == difference.aggregate_sha256
    assert evidence.approval_reference == "maintainer-decision-task-5-2026-07-15"

    report_only_evidence = validate_freeze_review(
        review,
        difference=difference,
        historical=None,
        regenerated=regenerated,
        discovery=discovery,
        current_git=GitMetadata(available=True, commit="a" * 40, dirty=False),
        actual_uv_lock_sha256="b" * 64,
    )
    assert report_only_evidence == evidence


@pytest.mark.parametrize(
    ("review_change", "git", "discovery_change", "message"),
    [
        ({"difference_report_sha256": "0" * 64}, None, {}, "difference"),
        ({"selection_rule_version": "wrong"}, None, {}, "selection rule"),
        ({"generation_git_commit": "c" * 40}, None, {}, "commit"),
        ({"uv_lock_sha256": "c" * 64}, None, {}, "uv.lock"),
        ({}, GitMetadata(available=True, commit="a" * 40, dirty=True), {}, "clean"),
        ({}, None, {"release_eligible": False}, "release-eligible"),
        ({}, None, {"generation_git_dirty": True}, "clean"),
    ],
)
def test_validate_freeze_review_fails_closed_on_stale_or_dirty_evidence(
    tmp_path: Path,
    review_change: dict[str, object],
    git: GitMetadata | None,
    discovery_change: dict[str, object],
    message: str,
) -> None:
    from protein_split_audit.cohort.freeze import FreezeGateError, validate_freeze_review

    historical, regenerated, difference, discovery, review = _freeze_inputs(tmp_path)
    changed_review = review.model_copy(update=review_change)
    changed_discovery = discovery.model_copy(update=discovery_change)

    with pytest.raises(FreezeGateError, match=message):
        validate_freeze_review(
            changed_review,
            difference=difference,
            historical=historical,
            regenerated=regenerated,
            discovery=changed_discovery,
            current_git=git or GitMetadata(available=True, commit="a" * 40, dirty=False),
            actual_uv_lock_sha256="b" * 64,
        )
