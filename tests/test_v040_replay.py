# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from click import unstyle
from typer.testing import CliRunner

from protein_split_audit.cli import app
from protein_split_audit.experiments.replay import compare_esm_replays


def _replay(root: Path, value: float) -> None:
    root.mkdir()
    np.save(root / "embeddings.npy", np.asarray([[value, 2.0]], dtype=np.float32))
    (root / "predictions.json").write_text('{"labels":["1.1"]}\n', encoding="utf-8")
    (root / "metrics.json").write_text('{"macro_f1":1.0}\n', encoding="utf-8")
    (root / "environment.json").write_text(
        '{"architecture":"arm64","operating_system":"Darwin","run_host":"host-a"}\n',
        encoding="utf-8",
    )
    (root / "resource_usage.json").write_text('{"elapsed_seconds":1.0}\n', encoding="utf-8")


def test_same_platform_esm_replay_requires_byte_identity(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _replay(first, 1.0)
    _replay(second, 1.0001)

    report = compare_esm_replays(first, second, tmp_path / "formal.json")

    assert report.byte_identical is False
    assert report.release_eligible is False
    assert report.replay_difference > 0


def test_cross_platform_esm_replay_is_diagnostic_only(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _replay(first, 1.0)
    _replay(second, 1.000001)

    report = compare_esm_replays(
        first,
        second,
        tmp_path / "diagnostic.json",
        cross_platform=True,
    )
    mapping = json.loads(report.output_path.read_bytes())

    assert report.release_eligible is False
    assert mapping["rtol"] == 1e-5
    assert mapping["atol"] == 1e-6
    assert set(mapping["diagnostics"]) == {
        "max_absolute_difference",
        "max_relative_difference",
        "metric_difference",
        "number_of_values_outside_tolerance",
        "prediction_disagreement_count",
    }


def test_same_platform_replay_compares_environment_identity_but_not_run_fields(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _replay(first, 1.0)
    _replay(second, 1.0)
    (second / "environment.json").write_text(
        '{"architecture":"arm64","operating_system":"Darwin","run_host":"host-b"}\n',
        encoding="utf-8",
    )
    (second / "resource_usage.json").write_text('{"elapsed_seconds":9.0}\n', encoding="utf-8")

    report = compare_esm_replays(first, second, tmp_path / "same.json")

    assert report.byte_identical is True

    (second / "environment.json").write_text(
        '{"architecture":"x86_64","operating_system":"Darwin","run_host":"host-b"}\n',
        encoding="utf-8",
    )
    changed = compare_esm_replays(first, second, tmp_path / "changed.json")
    assert changed.byte_identical is False
    assert changed.release_eligible is False


def test_replay_cli_exposes_explicit_esm_protocol_options() -> None:
    result = CliRunner().invoke(app, ["experiment", "replay-compare", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "--kind" in output
    assert "--cross-platform" in output
