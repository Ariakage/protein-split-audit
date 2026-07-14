# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typer.testing import CliRunner

from protein_split_audit import __version__
from protein_split_audit.cli import app

runner = CliRunner()


def test_version_option_reports_installed_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_current_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "data" in result.stdout
    assert "download" not in result.stdout
    assert "build" not in result.stdout
    assert "profile" not in result.stdout


def test_data_download_help_is_registered() -> None:
    result = runner.invoke(app, ["data", "download", "--help"])

    assert result.exit_code == 0
    assert "--config" in result.stdout
    assert "UniProt" in result.stdout


def test_data_build_help_is_registered() -> None:
    result = runner.invoke(app, ["data", "build", "--help"])

    assert result.exit_code == 0
    assert "--config" in result.stdout
    assert "candidate" in result.stdout.lower()


def test_data_profile_help_is_registered() -> None:
    result = runner.invoke(app, ["data", "profile", "--help"])

    assert result.exit_code == 0
    assert "--dataset" in result.stdout
    assert "--build-manifest" in result.stdout
    assert "--output-dir" in result.stdout
    assert "aggregate" in result.stdout.lower()


def test_doctor_succeeds_for_repository() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "ProteinSplitAudit version" in result.stdout
    assert "Python version" in result.stdout
    assert "Operating system" in result.stdout
    assert "Architecture" in result.stdout
    assert "Project root" in result.stdout
    assert "uv.lock" in result.stdout
    assert "Overall: PASS" in result.stdout
