# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from protein_split_audit.cli import app

PROJECT_ROOT = Path(__file__).parents[1]


def test_v040_finalize_test_denies_before_real_input() -> None:
    result = CliRunner().invoke(
        app,
        [
            "experiment",
            "finalize-test",
            "--config",
            str(PROJECT_ROOT / "configs/experiment/v040-test-gated.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "Real test access is not authorized" in result.output
