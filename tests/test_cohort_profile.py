# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from protein_split_audit.data.build_candidates import CANDIDATE_SCHEMA
from protein_split_audit.provenance import (
    BuildCounts,
    BuildManifest,
    serialize_json_model,
    sha256_bytes,
)


def _candidate_rows() -> list[dict[str, Any]]:
    first_sequence = "A" * 50
    second_sequence = "C" * 60
    return [
        {
            "primary_accession": "A00001",
            "entry_name": "FIRST_TEST",
            "protein_name": "Synthetic enzyme one",
            "organism_name": "Synthetic organism",
            "organism_id": 83333,
            "sequence": first_sequence,
            "sequence_length": len(first_sequence),
            "sequence_sha256": sha256_bytes(first_sequence.encode("ascii")),
            "ec_number": "2.7.1.1",
            "ec_level_2": "2.7",
            "duplicate_count": 1,
            "duplicate_accessions": ["A00001"],
            "source_page_number": 1,
            "source_row_number": 1,
        },
        {
            "primary_accession": "B00002",
            "entry_name": "SECOND_TEST",
            "protein_name": "Synthetic enzyme two",
            "organism_name": "Synthetic organism",
            "organism_id": 83333,
            "sequence": second_sequence,
            "sequence_length": len(second_sequence),
            "sequence_sha256": sha256_bytes(second_sequence.encode("ascii")),
            "ec_number": "1.1.1.1",
            "ec_level_2": "1.1",
            "duplicate_count": 1,
            "duplicate_accessions": ["B00002"],
            "source_page_number": 1,
            "source_row_number": 2,
        },
    ]


def _fasta_bytes(rows: list[dict[str, Any]]) -> bytes:
    lines: list[str] = []
    for row in rows:
        lines.extend(
            (
                ">sp|"
                f"{row['primary_accession']}|{row['entry_name']} "
                f"ec={row['ec_number']} taxon={row['organism_id']} "
                f"seq_sha256={row['sequence_sha256']}",
                str(row["sequence"]),
            )
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def _write_candidate_inputs(tmp_path: Path) -> tuple[Path, Path, Path, list[dict[str, Any]]]:
    rows = _candidate_rows()
    dataset = tmp_path / "candidate.parquet"
    fasta = tmp_path / "candidate.fasta"
    build_manifest = tmp_path / "candidate.build.json"
    pq.write_table(pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA), dataset)
    fasta.write_bytes(_fasta_bytes(rows))
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
        git_commit="5" * 40,
        git_dirty=False,
        python_version="3.12.0",
        uv_lock_sha256="6" * 64,
    )
    build_manifest.write_bytes(serialize_json_model(manifest))
    return dataset, build_manifest, fasta, rows


def _update_manifest_file_hash(build_manifest: Path, artifact: Path) -> None:
    manifest = json.loads(build_manifest.read_text(encoding="utf-8"))
    manifest["output_file_sha256"][artifact.name] = sha256_bytes(artifact.read_bytes())
    build_manifest.write_text(json.dumps(manifest), encoding="utf-8")


def _replace_fasta(fasta: Path, build_manifest: Path, content: bytes) -> None:
    fasta.write_bytes(content)
    _update_manifest_file_hash(build_manifest, fasta)


def _profile_lock_path(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    return resolved.parent / f".{resolved.name}.candidate-profile.lock"


def test_load_candidate_pool_maps_primary_accession_once(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)

    pool = load_candidate_pool(dataset, build_manifest, fasta)

    assert [record.accession for record in pool.records] == ["A00001", "B00002"]
    assert [record.sequence_sha256 for record in pool.records] == [
        row["sequence_sha256"] for row in rows
    ]
    assert not hasattr(pool.records[0], "primary_accession")


def test_load_candidate_pool_retains_validated_build_manifest(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    expected = BuildManifest.model_validate_json(build_manifest.read_bytes())

    pool = load_candidate_pool(dataset, build_manifest, fasta)
    build_manifest.unlink()

    assert pool.build_manifest == expected


def test_load_candidate_pool_rejects_dataset_hash_mismatch(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    manifest = json.loads(build_manifest.read_text(encoding="utf-8"))
    manifest["output_file_sha256"][dataset.name] = "0" * 64
    build_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="dataset hash"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_fasta_hash_mismatch(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    manifest = json.loads(build_manifest.read_text(encoding="utf-8"))
    manifest["output_file_sha256"][fasta.name] = "0" * 64
    build_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="FASTA hash"):
        load_candidate_pool(dataset, build_manifest, fasta)


@pytest.mark.parametrize(
    ("target_name", "error_type", "message"),
    (
        ("dataset", FileNotFoundError, "unable to hash candidate dataset"),
        ("fasta", PermissionError, "unable to hash candidate FASTA"),
    ),
)
def test_load_candidate_pool_normalizes_hash_io_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    error_type: type[OSError],
    message: str,
) -> None:
    import protein_split_audit.cohort.profile_cohort as profile_module
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    inputs = {"dataset": dataset, "fasta": fasta}
    target = inputs[target_name]
    original_error = error_type(f"private path: {target}")
    real_sha256_file = profile_module.sha256_file

    def failing_hash(path: Path) -> str:
        if path == target:
            raise original_error
        return real_sha256_file(path)

    monkeypatch.setattr(profile_module, "sha256_file", failing_hash)

    with pytest.raises(RuntimeError, match=message) as caught:
        load_candidate_pool(dataset, build_manifest, fasta)

    assert caught.value.__cause__ is original_error
    assert str(tmp_path) not in str(caught.value)


def test_load_candidate_pool_rejects_invalid_build_manifest(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    build_manifest.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid build manifest"):
        load_candidate_pool(dataset, build_manifest, fasta)


@pytest.mark.parametrize(
    ("missing_index", "message"),
    (
        (0, "candidate dataset not found"),
        (1, "build manifest not found"),
        (2, "candidate FASTA not found"),
    ),
)
def test_load_candidate_pool_uses_only_explicit_input_paths(
    tmp_path: Path,
    missing_index: int,
    message: str,
) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    paths = [dataset, build_manifest, fasta]
    paths[missing_index].unlink()
    (tmp_path / f"decoy{paths[missing_index].suffix}").write_bytes(b"not the explicit input")

    with pytest.raises(RuntimeError, match=message):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_missing_candidate_column(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    schema = CANDIDATE_SCHEMA.remove(CANDIDATE_SCHEMA.get_field_index("entry_name"))
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), dataset)
    _update_manifest_file_hash(build_manifest, dataset)

    with pytest.raises(RuntimeError, match="candidate schema"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_unreadable_candidate_parquet(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    dataset.write_bytes(b"not parquet")
    _update_manifest_file_hash(build_manifest, dataset)

    with pytest.raises(RuntimeError, match="unable to read candidate Parquet"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_nullable_candidate_field(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    field_index = CANDIDATE_SCHEMA.get_field_index("protein_name")
    schema = CANDIDATE_SCHEMA.set(
        field_index,
        pa.field("protein_name", pa.string(), nullable=True),
    )
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), dataset)
    _update_manifest_file_hash(build_manifest, dataset)

    with pytest.raises(RuntimeError, match="candidate schema"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_malformed_sequence_hash(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    rows[0]["sequence_sha256"] = "not-a-sha256"
    pq.write_table(pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA), dataset)
    _update_manifest_file_hash(build_manifest, dataset)
    _replace_fasta(fasta, build_manifest, _fasta_bytes(rows))

    with pytest.raises(RuntimeError, match="invalid candidate row"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_wrong_manifest_row_count(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    manifest = json.loads(build_manifest.read_text(encoding="utf-8"))
    manifest["counts"]["retained_candidates"] = 3
    build_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="row count"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_duplicate_accession(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    rows[1]["primary_accession"] = rows[0]["primary_accession"]
    pq.write_table(pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA), dataset)
    _update_manifest_file_hash(build_manifest, dataset)

    with pytest.raises(RuntimeError, match="duplicate accession"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_duplicate_sequence_hash(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    rows[1]["sequence"] = rows[0]["sequence"]
    rows[1]["sequence_length"] = rows[0]["sequence_length"]
    rows[1]["sequence_sha256"] = rows[0]["sequence_sha256"]
    pq.write_table(pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA), dataset)
    _update_manifest_file_hash(build_manifest, dataset)

    with pytest.raises(RuntimeError, match="duplicate sequence_sha256"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_non_ascii_fasta(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    content = _fasta_bytes(rows).replace(b"FIRST_TEST", "FÉRST_TEST".encode())
    _replace_fasta(fasta, build_manifest, content)

    with pytest.raises(RuntimeError, match="ASCII FASTA"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_fasta_header_disagreement(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    content = _fasta_bytes(rows).replace(b"FIRST_TEST", b"WRONG_TEST")
    _replace_fasta(fasta, build_manifest, content)

    with pytest.raises(RuntimeError, match="FASTA header/order"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_fasta_record_order_disagreement(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    _replace_fasta(fasta, build_manifest, _fasta_bytes(list(reversed(rows))))

    with pytest.raises(RuntimeError, match="FASTA header/order"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_fasta_sequence_hash_disagreement(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    content = _fasta_bytes(rows).replace(b"A" * 50 + b"\n", b"G" * 50 + b"\n")
    _replace_fasta(fasta, build_manifest, content)

    with pytest.raises(RuntimeError, match="FASTA sequence hash"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_load_candidate_pool_rejects_fasta_sequence_length_disagreement(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import load_candidate_pool

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    content = _fasta_bytes(rows).replace(b"A" * 50 + b"\n", b"A" * 49 + b"\n")
    _replace_fasta(fasta, build_manifest, content)

    with pytest.raises(RuntimeError, match="FASTA sequence length"):
        load_candidate_pool(dataset, build_manifest, fasta)


def test_profile_candidate_pool_returns_deterministic_class_and_length_summaries(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))

    assert profile.candidate_count == 2
    assert [row.model_dump() for row in profile.ec_level_2_class_counts] == [
        {"ec_level_2": "1.1", "candidate_count": 1},
        {"ec_level_2": "2.7", "candidate_count": 1},
    ]
    assert profile.sequence_length_summary.model_dump() == {
        "count": 2,
        "maximum": 60,
        "mean": 55.0,
        "median": 55.0,
        "minimum": 50,
        "quantiles": {
            "0.05": 50.5,
            "0.25": 52.5,
            "0.50": 55.0,
            "0.75": 57.5,
            "0.95": 59.5,
        },
    }


def test_write_candidate_profile_publishes_only_three_aggregate_artifacts(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    output_dir = tmp_path / "profile"

    paths = write_candidate_profile(profile, output_dir)

    assert paths == (
        output_dir / "profile_summary.json",
        output_dir / "ec_level_2_class_counts.csv",
        output_dir / "sequence_length_summary.json",
    )
    assert {path.name for path in output_dir.iterdir()} == {path.name for path in paths}
    source = {
        "build_manifest_sha256": profile.build_manifest_sha256,
        "dataset_sha256": profile.dataset_sha256,
        "fasta_sha256": profile.fasta_sha256,
    }
    summary = json.loads(paths[0].read_text(encoding="utf-8"))
    assert summary == {
        "candidate_count": 2,
        "candidate_dataset_only": True,
        "ec_level_2_class_count": 2,
        "no_split_or_benchmark_results": True,
        "profile_schema_version": 1,
        "source": source,
    }
    with paths[1].open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream)) == [
            {
                "ec_level_2": "1.1",
                "candidate_count": "1",
                **source,
            },
            {
                "ec_level_2": "2.7",
                "candidate_count": "1",
                **source,
            },
        ]
    length_summary = json.loads(paths[2].read_text(encoding="utf-8"))
    assert length_summary == {
        "profile_schema_version": 1,
        "quantile_method": "linear_interpolation_rank_n_minus_1",
        "source": source,
        "statistics": profile.sequence_length_summary.model_dump(),
    }
    assert all(path.read_bytes().endswith(b"\n") for path in paths)


def test_candidate_profile_outputs_are_byte_deterministic_and_do_not_leak_rows(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))

    first = write_candidate_profile(profile, tmp_path / "first")
    second = write_candidate_profile(profile, tmp_path / "second")

    assert [path.read_bytes() for path in first] == [path.read_bytes() for path in second]
    content = b"".join(path.read_bytes() for path in first)
    assert str(tmp_path).encode() not in content
    assert b"built_at_utc" not in content
    assert b"primary_accession" not in content
    for row in rows:
        assert str(row["primary_accession"]).encode() not in content
        assert str(row["sequence_sha256"]).encode() not in content
        assert str(row["sequence"]).encode() not in content


def test_empty_candidate_pool_has_defined_aggregate_outputs(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    pq.write_table(pa.Table.from_pylist([], schema=CANDIDATE_SCHEMA), dataset)
    fasta.write_bytes(b"")
    manifest = json.loads(build_manifest.read_text(encoding="utf-8"))
    manifest["output_file_sha256"][dataset.name] = sha256_bytes(dataset.read_bytes())
    manifest["output_file_sha256"][fasta.name] = sha256_bytes(fasta.read_bytes())
    manifest["counts"] = {
        "input_records": 0,
        "after_ec_filter": 0,
        "after_sequence_filter": 0,
        "after_conflict_filter": 0,
        "retained_candidates": 0,
    }
    build_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    paths = write_candidate_profile(profile, tmp_path / "empty-profile")

    assert profile.candidate_count == 0
    assert profile.ec_level_2_class_counts == ()
    assert profile.sequence_length_summary.model_dump() == {
        "count": 0,
        "maximum": None,
        "mean": None,
        "median": None,
        "minimum": None,
        "quantiles": {
            "0.05": None,
            "0.25": None,
            "0.50": None,
            "0.75": None,
            "0.95": None,
        },
    }
    assert paths[1].read_text(encoding="utf-8").splitlines() == [
        "ec_level_2,candidate_count,dataset_sha256,build_manifest_sha256,fasta_sha256"
    ]


def test_write_candidate_profile_refuses_to_overwrite_any_artifact(tmp_path: Path) -> None:
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    output_dir = tmp_path / "profile"
    output_dir.mkdir()
    existing = output_dir / "profile_summary.json"
    existing.write_text("do not replace\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_candidate_profile(profile, output_dir)

    assert existing.read_text(encoding="utf-8") == "do not replace\n"
    assert list(output_dir.iterdir()) == [existing]


def test_write_candidate_profile_does_not_clobber_target_created_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cohort.profile_cohort as profile_module
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    output_dir = tmp_path / "profile"
    competitor_content = b"created by a concurrent writer\n"
    real_link = profile_module.os.link
    real_replace = profile_module.os.replace

    def racing_link(source: Path, destination: Path) -> None:
        destination.write_bytes(competitor_content)
        real_link(source, destination)

    def racing_replace(source: Path, destination: Path) -> None:
        destination.write_bytes(competitor_content)
        real_replace(source, destination)

    monkeypatch.setattr(profile_module.os, "link", racing_link)
    monkeypatch.setattr(profile_module.os, "replace", racing_replace)

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_candidate_profile(profile, output_dir)

    assert (output_dir / "profile_summary.json").read_bytes() == competitor_content
    assert not (output_dir / "ec_level_2_class_counts.csv").exists()
    assert not (output_dir / "sequence_length_summary.json").exists()


def test_write_candidate_profile_rejects_cooperating_concurrent_writer(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    output_dir = tmp_path / "profile"
    lock_path = _profile_lock_path(output_dir)

    with lock_path.open("a+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already in progress"):
            write_candidate_profile(profile, output_dir)

    assert not output_dir.exists()


def test_write_candidate_profile_holds_cooperative_lock_during_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cohort.profile_cohort as profile_module
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    output_dir = tmp_path / "profile"
    lock_path = _profile_lock_path(output_dir)
    real_link = profile_module.os.link
    real_unlink = Path.unlink
    link_count = 0
    lock_was_held: bool | None = None

    def fail_second_link(source: Path, destination: Path) -> None:
        nonlocal link_count
        link_count += 1
        if link_count == 2:
            raise OSError("synthetic publication failure")
        real_link(source, destination)

    def probe_lock_before_unlink(path: Path) -> None:
        nonlocal lock_was_held
        if path == output_dir / "profile_summary.json":
            with lock_path.open("a+b") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    lock_was_held = True
                else:
                    lock_was_held = False
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        real_unlink(path)

    monkeypatch.setattr(profile_module.os, "link", fail_second_link)
    monkeypatch.setattr(Path, "unlink", probe_lock_before_unlink)

    with pytest.raises(RuntimeError, match="failed to publish"):
        write_candidate_profile(profile, output_dir)

    assert lock_was_held is True
    assert not any(path.is_file() for path in output_dir.iterdir())


def test_write_candidate_profile_rolls_back_partial_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cohort.profile_cohort as profile_module
    from protein_split_audit.cohort.profile_cohort import (
        load_candidate_pool,
        profile_candidate_pool,
        write_candidate_profile,
    )

    dataset, build_manifest, fasta, _rows = _write_candidate_inputs(tmp_path)
    profile = profile_candidate_pool(load_candidate_pool(dataset, build_manifest, fasta))
    output_dir = tmp_path / "profile"
    real_link = profile_module.os.link
    call_count = 0

    def fail_second_link(source: Path, destination: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("synthetic publication failure")
        real_link(source, destination)

    monkeypatch.setattr(profile_module.os, "link", fail_second_link)

    with pytest.raises(RuntimeError, match="failed to publish"):
        write_candidate_profile(profile, output_dir)

    assert not any(path.is_file() for path in output_dir.iterdir())
