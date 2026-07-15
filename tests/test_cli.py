# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from rich.text import Text
from typer.testing import CliRunner

from protein_split_audit import __version__
from protein_split_audit.cli import app

runner = CliRunner()
colored_terminal = {"TERM": "xterm-256color", "FORCE_COLOR": "1"}


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
    result = runner.invoke(
        app,
        ["data", "download", "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "--config" in output
    assert "UniProt" in output


def test_data_build_help_is_registered() -> None:
    result = runner.invoke(
        app,
        ["data", "build", "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "--config" in output
    assert "candidate" in output.lower()


def test_data_profile_help_is_registered() -> None:
    result = runner.invoke(
        app,
        ["data", "profile", "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "--dataset" in output
    assert "--build-manifest" in output
    assert "--output-dir" in output
    assert "aggregate" in output.lower()


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
