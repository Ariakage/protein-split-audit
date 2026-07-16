# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import protein_split_audit.cli as cli
from protein_split_audit.embeddings.model_registry import build_snapshot_manifest
from protein_split_audit.provenance import sha256_file
from tests.test_model_snapshot import _config, _snapshot

runner = CliRunner()


def test_base_cli_import_does_not_require_torch() -> None:
    script = """
import builtins
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise ModuleNotFoundError('torch deliberately unavailable')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import protein_split_audit.cli
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_embedding_cli_help_lists_asset_commands() -> None:
    result = runner.invoke(cli.app, ["embedding", "--help"])

    assert result.exit_code == 0
    assert "fetch" in result.stdout
    assert "verify-model" in result.stdout
    assert "extract" in result.stdout


def test_embedding_fetch_writes_sanitized_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    _snapshot(snapshot)
    config = _config(snapshot)
    weight_hash = sha256_file(snapshot / "model.safetensors")
    config = config.model_copy(
        update={"model": config.model.model_copy(update={"expected_weight_sha256": weight_hash})}
    )
    manifest = build_snapshot_manifest(
        config,
        downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
    )
    config_path = tmp_path / "embedding.yaml"
    config_path.write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.setattr(cli, "find_project_root", lambda _path: tmp_path)
    monkeypatch.setattr(cli, "load_embedding_config", lambda _path: config)
    monkeypatch.setattr(cli, "fetch_model_snapshot", lambda _config, **_kwargs: manifest)

    result = runner.invoke(cli.app, ["embedding", "fetch", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    manifest_path = tmp_path / "data/manifests/models/esm2-35m.snapshot.json"
    assert manifest_path.is_file()
    assert str(tmp_path) not in manifest_path.read_text(encoding="utf-8")
