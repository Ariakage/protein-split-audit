# SPDX-License-Identifier: Apache-2.0

"""Repository-policy checks for preserved historical release artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
LEGACY_DIRECTORY = PROJECT_ROOT / "results/released/v0.1.0/legacy"
LEGACY_DEDUPLICATION_SHA256 = "7dcdca22b828dcec764e52b14552cb04b775f81242b778aa84737d70a31fffcd"
HISTORICAL_BUILD_MANIFEST_SHA256 = (
    "6b4fdc5064d5b413160462fdcd3f93e4f179dcf63969b2c1e23bf371205bcd22"
)


def test_legacy_deduplication_map_is_archived_with_exact_historical_bytes() -> None:
    archived = LEGACY_DIRECTORY / "pilot.deduplication.json"

    assert not (PROJECT_ROOT / "data/manifests/pilot.deduplication.json").exists()
    assert archived.is_file()
    assert sha256_file(archived) == LEGACY_DEDUPLICATION_SHA256


def test_legacy_deduplication_marker_is_deterministic_and_explicit() -> None:
    marker_path = LEGACY_DIRECTORY / "LEGACY_ARTIFACT.json"
    expected = {
        "artifact_file": "pilot.deduplication.json",
        "artifact_sha256": LEGACY_DEDUPLICATION_SHA256,
        "contains_accession_level_rows": True,
        "contains_raw_sequences": False,
        "github_release_asset": False,
        "introduced_by_commit": "92f47d2ad0927288aae099f1cdd880989f6be889",
        "legacy": True,
        "legacy_schema_version": 1,
        "original_git_path": "data/manifests/pilot.deduplication.json",
        "purpose": "historical-v0.1-exact-sequence-alias-audit",
        "retained_tags": ["v0.1.0", "v0.1.1"],
        "use_as_v0_2_input": False,
    }
    expected_bytes = (
        json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()

    assert marker_path.read_bytes() == expected_bytes


def test_active_deduplication_output_is_ignored_without_changing_historical_manifest() -> None:
    ignore_lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    historical_manifest = PROJECT_ROOT / "data/manifests/pilot.build.json"

    assert "/data/manifests/pilot.deduplication.json" in ignore_lines
    assert sha256_file(historical_manifest) == HISTORICAL_BUILD_MANIFEST_SHA256
