# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
RELEASE_ROOT = PROJECT_ROOT / "results/released/v0.2.0"


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _walk_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _walk_keys(child)}
    return set()


def test_v020_release_bundle_has_exact_required_aggregate_files_and_checksums() -> None:
    required = {
        "candidate-regeneration-difference.json",
        "cluster30.audit.json",
        "cluster30.split.json",
        "cluster50.audit.json",
        "cluster50.split.json",
        "cluster70.audit.json",
        "cluster70.split.json",
        "pilot-v1-freeze-review.json",
        "pilot-v1.cluster30.json",
        "pilot-v1.cluster50.json",
        "pilot-v1.cluster70.json",
        "pilot-v1.cohort.json",
        "provenance.json",
        "random.audit.json",
        "random.split.json",
        "split_summary.json",
    }
    actual = {path.name for path in RELEASE_ROOT.glob("*.json")}
    assert actual == required

    checksum_rows = (RELEASE_ROOT / "CHECKSUMS.sha256").read_text().splitlines()
    assert len(checksum_rows) == len(required)
    for row in checksum_rows:
        digest, filename = row.split("  ", maxsplit=1)
        assert filename in required
        assert sha256_file(RELEASE_ROOT / filename) == digest


def test_v020_release_json_is_aggregate_only_and_path_safe() -> None:
    for path in sorted(RELEASE_ROOT.glob("*.json")):
        content = path.read_text(encoding="utf-8")
        document = json.loads(content)
        keys = _walk_keys(document)
        assert "accession" not in keys
        assert "sequence" not in keys
        assert "sequence_sha256" not in keys
        assert "timestamp_utc" not in keys
        assert "/Users/" not in content
        assert "ariakage" not in content.lower()


def test_v020_release_notes_and_audit_gates_remain_consistent() -> None:
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = (PROJECT_ROOT / "docs/releases/v0.2.0.md").read_text(encoding="utf-8")
    assert "## 0.2.0 - 2026-07-15" in changelog
    assert "# ProteinSplitAudit v0.2.0" in notes

    summary = json.loads((RELEASE_ROOT / "split_summary.json").read_bytes())
    for name in ("cluster70", "cluster50", "cluster30"):
        assert summary["audits"][name]["threshold_violation_count"] == 0
        assert summary["splits"][name]["component_crossings"] == 0
