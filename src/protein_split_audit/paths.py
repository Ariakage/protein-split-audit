# SPDX-License-Identifier: Apache-2.0

"""Project path discovery and filesystem checks."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_MARKERS = ("pyproject.toml", "uv.lock")


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the nearest ancestor containing all project markers."""

    candidate = (start or Path.cwd()).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent

    for directory in (candidate, *candidate.parents):
        if all((directory / marker).is_file() for marker in PROJECT_MARKERS):
            return directory
    return None


def is_writable_directory(path: Path) -> bool:
    """Return whether an existing directory is writable."""

    resolved = path.expanduser().resolve()
    return resolved.is_dir() and os.access(resolved, os.W_OK)
