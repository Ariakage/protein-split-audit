# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.paths import find_project_root


def test_find_project_root_from_nested_directory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    assert find_project_root(nested) == root.resolve()


def test_find_project_root_returns_none_without_markers(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_project_root(nested) is None
