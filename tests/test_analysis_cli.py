# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typer.testing import CliRunner

from protein_split_audit.cli import app


def test_analysis_and_report_help_expose_only_frozen_interfaces() -> None:
    runner = CliRunner()
    analysis = runner.invoke(app, ["analysis", "--help"])
    report = runner.invoke(app, ["report", "--help"])

    assert analysis.exit_code == 0
    assert all(
        command in analysis.stdout for command in ("verify-inputs", "run", "replay", "aggregate")
    )
    assert "--allow-dirty" not in analysis.stdout
    assert "--force" not in analysis.stdout
    assert report.exit_code == 0
    assert "figures" in report.stdout

    run_help = runner.invoke(
        app,
        ["analysis", "run", "--help"],
        env={"COLUMNS": "200"},
    )
    assert run_help.exit_code == 0
    assert "analysis-r1-a" in run_help.stdout
    assert "analysis-r1-b" in run_help.stdout


def test_superseded_attestation_cannot_authorize_generation_a5() -> None:
    result = CliRunner().invoke(
        app,
        [
            "analysis",
            "verify-inputs",
            "--config",
            "configs/analysis/v060-post-test-analysis.yaml",
            "--attestation",
            "docs/attestations/v0.6.0-analysis-freeze.yaml",
        ],
    )
    assert result.exit_code != 0
    assert "not authorized" in result.output.lower()
