# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protein_split_audit.cli import app
from protein_split_audit.demo import DemoError, run_synthetic_demo

runner = CliRunner()


def test_synthetic_demo_is_deterministic_and_public_safe(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = run_synthetic_demo(first)
    second_result = run_synthetic_demo(second)

    assert first_result == second_result
    assert {path.name for path in first.iterdir() if path.is_file()} == {
        ".psaudit-publication.lock",
        "README.md",
        "demo_manifest.json",
        "split_summary.csv",
    }
    for name in ("README.md", "demo_manifest.json", "split_summary.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    manifest = json.loads((first / "demo_manifest.json").read_bytes())
    assert manifest["artifact_kind"] == "synthetic_methods_demo"
    assert manifest["evidence_scope"] == "software_smoke_test_only"
    assert manifest["dataset"]["sequence_count"] == 90
    assert manifest["dataset"]["class_count"] == 3
    assert manifest["dataset"]["component_count"] == 45
    assert manifest["splits"]["cluster30"]["component_crossings"] == 0
    assert manifest["splits"]["random"]["component_crossings"] > 0

    combined = b"".join(
        (first / name).read_bytes()
        for name in ("README.md", "demo_manifest.json", "split_summary.csv")
    )
    assert b"/Users/" not in combined
    assert b"/home/" not in combined
    assert b'sequence"' not in combined
    assert b"accession" not in combined


def test_synthetic_demo_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    run_synthetic_demo(output)

    with pytest.raises(DemoError, match="Refusing to overwrite"):
        run_synthetic_demo(output)


def test_demo_cli_help_and_run(tmp_path: Path) -> None:
    help_result = runner.invoke(app, ["demo", "run", "--help"])

    assert help_result.exit_code == 0
    assert "--output-dir" in help_result.stdout
    assert "synthetic" in help_result.stdout.lower()

    output = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "run", "--output-dir", str(output)])

    assert result.exit_code == 0
    assert "Synthetic demo complete" in result.stdout
    assert (output / "demo_manifest.json").is_file()
