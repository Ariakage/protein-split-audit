# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from protein_split_audit.data.profile import (
    ProfileError,
    profile_candidate_dataset,
    summarize_organisms,
    summarize_sequence_lengths,
)
from protein_split_audit.provenance import sha256_file
from tests.test_build_candidates import run_build

PROFILE_FILENAMES = {
    "profile_summary.json",
    "ec_level_2_class_counts.csv",
    "sequence_length_summary.json",
    "organism_summary_top100.csv",
    "filtering_flow.csv",
    "deduplication_summary.json",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_fixture_tsv_builds_through_profile_summaries(tmp_path: Path) -> None:
    build, _source = run_build(tmp_path)
    output_dir = tmp_path / "results/runs/profile-pilot"

    result = profile_candidate_dataset(
        dataset_path=build.parquet_path,
        build_manifest_path=build.manifest_path,
        output_dir=output_dir,
    )

    assert {path.name for path in result.artifact_paths} == PROFILE_FILENAMES
    assert {path.name for path in output_dir.iterdir()} == PROFILE_FILENAMES

    profile = json.loads(result.profile_summary_path.read_text(encoding="utf-8"))
    lengths = json.loads(result.sequence_length_summary_path.read_text(encoding="utf-8"))
    deduplication = json.loads(result.deduplication_summary_path.read_text(encoding="utf-8"))
    ec_counts = read_csv(result.ec_level_2_class_counts_path)
    organisms = read_csv(result.organism_summary_top100_path)
    filtering = read_csv(result.filtering_flow_path)

    assert profile["candidate_count"] == 2
    assert profile["ec_level_2_class_count"] == 2
    assert profile["organism_count"] == 1
    assert profile["candidate_dataset_only"] is True
    assert profile["no_split_or_benchmark_results"] is True
    assert lengths["statistics"] == {
        "count": 2,
        "maximum": 50,
        "mean": 50.0,
        "median": 50.0,
        "minimum": 50,
        "quantiles": {
            "0.05": 50.0,
            "0.25": 50.0,
            "0.50": 50.0,
            "0.75": 50.0,
            "0.95": 50.0,
        },
    }
    assert deduplication["duplicate_group_count"] == 1
    assert deduplication["duplicate_alias_count"] == 1
    assert deduplication["conflict_group_count"] == 1
    assert deduplication["conflicting_record_count"] == 2
    assert [(row["ec_level_2"], row["candidate_count"]) for row in ec_counts] == [
        ("2.7", "1"),
        ("3.3", "1"),
    ]
    assert [(row["organism_id"], row["candidate_count"]) for row in organisms] == [("83333", "2")]
    assert [(row["stage"], row["record_count"]) for row in filtering] == [
        ("input_records", "9"),
        ("after_ec_filter", "6"),
        ("after_sequence_filter", "5"),
        ("after_conflict_filter", "3"),
        ("retained_candidates", "2"),
    ]


def test_every_profile_artifact_references_input_hashes_without_private_data(
    tmp_path: Path,
) -> None:
    build, _source = run_build(tmp_path)
    result = profile_candidate_dataset(
        dataset_path=build.parquet_path,
        build_manifest_path=build.manifest_path,
        output_dir=tmp_path / "results/runs/profile-pilot",
    )
    dataset_hash = sha256_file(build.parquet_path)
    manifest_hash = sha256_file(build.manifest_path)

    for path in result.artifact_paths:
        content = path.read_text(encoding="utf-8")
        assert dataset_hash in content
        assert manifest_hash in content
        assert str(tmp_path) not in content
        assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in content


def test_profile_outputs_are_byte_deterministic(tmp_path: Path) -> None:
    first_build, _ = run_build(tmp_path / "first")
    second_build, _ = run_build(tmp_path / "second")
    first = profile_candidate_dataset(
        dataset_path=first_build.parquet_path,
        build_manifest_path=first_build.manifest_path,
        output_dir=tmp_path / "first/results/runs/profile-pilot",
    )
    second = profile_candidate_dataset(
        dataset_path=second_build.parquet_path,
        build_manifest_path=second_build.manifest_path,
        output_dir=tmp_path / "second/results/runs/profile-pilot",
    )

    assert {path.name: path.read_bytes() for path in first.artifact_paths} == {
        path.name: path.read_bytes() for path in second.artifact_paths
    }


def test_profile_rejects_dataset_not_named_in_or_matching_manifest(tmp_path: Path) -> None:
    build, _source = run_build(tmp_path)
    build.parquet_path.write_bytes(build.parquet_path.read_bytes() + b"tampered")

    with pytest.raises(ProfileError, match="hash does not match"):
        profile_candidate_dataset(
            dataset_path=build.parquet_path,
            build_manifest_path=build.manifest_path,
            output_dir=tmp_path / "results/runs/profile-pilot",
        )


def test_profile_refuses_to_overwrite_outputs(tmp_path: Path) -> None:
    build, _source = run_build(tmp_path)
    output_dir = tmp_path / "results/runs/profile-pilot"
    profile_candidate_dataset(
        dataset_path=build.parquet_path,
        build_manifest_path=build.manifest_path,
        output_dir=output_dir,
    )

    with pytest.raises(ProfileError, match="refusing to overwrite"):
        profile_candidate_dataset(
            dataset_path=build.parquet_path,
            build_manifest_path=build.manifest_path,
            output_dir=output_dir,
        )


def test_empty_sequence_statistics_use_null_for_undefined_values() -> None:
    assert summarize_sequence_lengths([]) == {
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


def test_organism_summary_is_limited_to_deterministic_top_100() -> None:
    organisms = [(identifier, f"Organism {identifier:03d}") for identifier in range(105)]
    organisms.extend([(104, "Organism 104"), (104, "Organism 104")])

    summary = summarize_organisms(organisms)

    assert len(summary) == 100
    assert summary[0] == {
        "candidate_count": 3,
        "organism_id": 104,
        "organism_name": "Organism 104",
        "rank": 1,
    }
    assert [row["organism_id"] for row in summary[1:]] == list(range(99))
