# SPDX-License-Identifier: Apache-2.0

"""Path-safe experiment environment provenance."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from protein_split_audit import __version__
from protein_split_audit.paths import find_project_root
from protein_split_audit.provenance import git_metadata, sha256_file

EXPERIMENT_MANIFEST_SCHEMA_VERSION = 1


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def environment_mapping(config_path: Path) -> dict[str, object]:
    """Return versioned environment data without timestamps or private paths."""

    root = find_project_root(config_path)
    git = git_metadata(root) if root is not None else None
    lock = root / "uv.lock" if root is not None else None
    return {
        "architecture": platform.machine(),
        "dependencies": {
            name: _package_version(name)
            for name in ("joblib", "numpy", "psutil", "pyarrow", "scikit-learn", "scipy")
        },
        "git_commit": git.commit if git is not None else None,
        "git_dirty": git.dirty if git is not None else None,
        "operating_system": platform.system(),
        "python_version": platform.python_version(),
        "software_version": __version__,
        "uv_lock_sha256": sha256_file(lock) if lock is not None and lock.is_file() else None,
        "version_info": list(sys.version_info[:3]),
    }


__all__ = ["EXPERIMENT_MANIFEST_SCHEMA_VERSION", "environment_mapping"]
