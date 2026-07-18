# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_v060_ci_keeps_locked_offline_quality_and_wheel_checks() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for command in (
        "uv lock --check",
        "uv sync --locked --group dev --extra esm",
        "uv run --locked --extra esm ruff check .",
        "uv run --locked --extra esm ruff format --check .",
        "uv run --locked --extra esm mypy src",
        "uv run --locked --extra esm pytest -v",
        "uv build --clear",
        'uv run --isolated --no-project --with "$WHEEL" psaudit analysis --help',
        'uv run --isolated --no-project --with "$WHEEL" psaudit report --help',
    ):
        assert command in workflow
    assert "protein_split_audit-0.6.0-*.whl" in workflow
    assert "HF_HUB_OFFLINE" in workflow
    assert "TRANSFORMERS_OFFLINE" in workflow
    assert "UV_OFFLINE" in workflow
    assert "NO_PROXY" not in workflow
    assert "psaudit analysis run" not in workflow
    assert "psaudit experiment test-matrix" not in workflow


def test_v060_tests_use_an_application_level_network_guard() -> None:
    guard = (PROJECT_ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    assert "deny_network" in guard
    assert "socket" in guard
    assert "NO_PROXY" not in guard
