# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from click import unstyle
from typer.testing import CliRunner

from protein_split_audit.cli import app

PROJECT_ROOT = Path(__file__).parents[1]


def test_ci_uses_locked_offline_checks_and_official_isolated_wheel_pattern() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    for command in (
        "uv lock --check",
        "uv sync --locked --group dev --extra esm",
        "uv run --locked --extra esm ruff check .",
        "uv run --locked --extra esm ruff format --check .",
        "uv run --locked --extra esm mypy src",
        "uv run --locked --extra esm pytest -v",
        "uv build --clear",
        'uv run --isolated --no-project --with "$WHEEL" psaudit --version',
    ):
        assert command in workflow
    assert "UV_OFFLINE" in workflow
    assert "TRANSFORMERS_OFFLINE" in workflow
    assert "HF_HUB_OFFLINE" in workflow
    assert "NO_PROXY" not in workflow
    assert "psaudit experiment test-matrix" not in workflow


def test_ci_primes_the_isolated_wheel_environment_before_offline_smoke() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    prime_start = workflow.index("Prime isolated wheel dependency cache")
    smoke_start = workflow.index("Smoke-test wheel in an offline isolated environment")
    assert prime_start < smoke_start

    prime_block = workflow[prime_start:smoke_start]
    assert (
        'uv run --isolated --no-project --with "$WHEEL" python -c '
        '"import sys; assert sys.version_info[:2] == (3, 12)"'
    ) in prime_block
    assert "UV_OFFLINE" not in prime_block

    smoke_block = workflow[smoke_start:]
    assert 'uv run --isolated --no-project --with "$WHEEL" psaudit --version' in smoke_block
    assert 'UV_OFFLINE: "true"' in smoke_block


def test_formal_test_cli_has_no_override_and_denies_generation_a() -> None:
    runner = CliRunner()
    help_result = runner.invoke(app, ["experiment", "test-matrix", "--help"])
    output = unstyle(help_result.output)

    assert help_result.exit_code == 0
    assert "--config" in output
    for forbidden in (
        "--resume",
        "--split",
        "--method",
        "--seed",
        "--output",
        "--attestation",
        "--allow-dirty",
        "--authorize-test",
    ):
        assert forbidden not in output

    denied = runner.invoke(
        app,
        [
            "experiment",
            "test-matrix",
            "--config",
            str(PROJECT_ROOT / "configs/experiment/v050-test.yaml"),
        ],
    )
    assert denied.exit_code == 1
    assert "Real test access is not authorized" in unstyle(denied.output)


def test_application_level_network_guard_is_active_for_tests() -> None:
    guard = (PROJECT_ROOT / "tests/conftest.py").read_text(encoding="utf-8")

    assert "socket" in guard
    assert "deny_network" in guard
    assert "NO_PROXY" not in guard
