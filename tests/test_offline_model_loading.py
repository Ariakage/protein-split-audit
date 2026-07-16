# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from protein_split_audit.embeddings.model_registry import (
    APPROVED_SNAPSHOT_FILES,
    fetch_model_snapshot,
)
from tests.test_model_snapshot import _config


def test_fetch_materializes_only_the_approved_files(tmp_path: Path) -> None:
    source = tmp_path / "hub-cache"
    source.mkdir()
    for name in APPROVED_SNAPSHOT_FILES:
        (source / name).write_bytes(b"weights" if name == "model.safetensors" else name.encode())
    (source / "README.md").write_text("not approved", encoding="utf-8")
    destination = tmp_path / "canonical"
    config = _config(destination)
    weight_hash = __import__("hashlib").sha256(b"weights").hexdigest()
    config = config.model_copy(
        update={"model": config.model.model_copy(update={"expected_weight_sha256": weight_hash})}
    )
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fake_download(*, repo_id: str, revision: str, allow_patterns: list[str]) -> str:
        calls.append((repo_id, revision, tuple(allow_patterns)))
        return str(source)

    manifest = fetch_model_snapshot(
        config,
        downloader=fake_download,
        downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert calls == [(config.model.repository, config.model.revision, APPROVED_SNAPSHOT_FILES)]
    assert tuple(path.name for path in sorted(destination.iterdir())) == APPROVED_SNAPSHOT_FILES
    assert manifest.model_weight_sha256 == weight_hash


def test_fetch_refuses_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "canonical"
    destination.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        fetch_model_snapshot(
            _config(destination),
            downloader=lambda **_kwargs: str(tmp_path / "unused"),
            downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_fetch_accepts_hub_cache_symlinks_but_materializes_regular_files(tmp_path: Path) -> None:
    blobs = tmp_path / "blobs"
    source = tmp_path / "hub-snapshot"
    blobs.mkdir()
    source.mkdir()
    for name in APPROVED_SNAPSHOT_FILES:
        blob = blobs / name
        blob.write_bytes(b"weights" if name == "model.safetensors" else name.encode())
        (source / name).symlink_to(blob)
    destination = tmp_path / "canonical"
    config = _config(destination)
    weight_hash = __import__("hashlib").sha256(b"weights").hexdigest()
    config = config.model_copy(
        update={"model": config.model.model_copy(update={"expected_weight_sha256": weight_hash})}
    )

    fetch_model_snapshot(
        config,
        downloader=lambda **_kwargs: str(source),
        downloaded_at_utc=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert all(path.is_file() and not path.is_symlink() for path in destination.iterdir())
