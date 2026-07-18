# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protein_split_audit.analysis.aggregate import write_deterministic_bundle
from protein_split_audit.analysis.replay import (
    AnalysisReplayError,
    compare_analysis_replays,
    require_verified_analysis_replay,
)


def _run(path: Path, value: bytes = b"a,b\n1,2\n") -> None:
    write_deterministic_bundle(
        path,
        {
            "summary.csv": value,
            "analysis_manifest.json": b'{"schema_version":1}\n',
        },
    )
    (path / "run_provenance.json").write_text(
        '{"started_at_utc":"different by design"}\n', encoding="utf-8"
    )


def test_replay_ignores_only_run_provenance_and_issues_capability(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    _run(first)
    _run(second)
    (second / "run_provenance.json").write_text("{}\n", encoding="utf-8")
    output = tmp_path / "replay.json"

    result = compare_analysis_replays(first, second, output)

    require_verified_analysis_replay(result.authorization)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["deterministic_mismatch_count"] == 0
    assert report["aggregate_authorized"] is True
    assert report["excluded_files"] == {
        "run_provenance.json": "run-specific timestamp and local execution details"
    }


def test_replay_rejects_any_deterministic_difference(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    _run(first)
    _run(second, b"a,b\n1,3\n")

    with pytest.raises(AnalysisReplayError, match="deterministic mismatch"):
        compare_analysis_replays(first, second, tmp_path / "replay.json")
    assert not (tmp_path / "replay.json").exists()


def test_replay_capability_cannot_be_forged() -> None:
    with pytest.raises(AnalysisReplayError, match="not authorized"):
        require_verified_analysis_replay(object())
