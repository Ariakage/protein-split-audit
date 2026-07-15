# SPDX-License-Identifier: Apache-2.0

"""Deterministic content comparison for two Validation matrix replays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from protein_split_audit.provenance import sha256_file

_EXCLUDED = frozenset({"COMPLETE.json", "environment.json", "resource_usage.json", "run.log"})


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """Summary of deterministic artifact equality."""

    byte_identical: bool
    compared_file_count: int
    mismatch_count: int
    output_path: Path


def _content_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ValueError("Validation replay directory is missing")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in _EXCLUDED
    }


def compare_validation_replays(first: Path, second: Path, output: Path) -> ReplayReport:
    """Compare byte-level deterministic artifacts and write a path-safe report."""

    if output.exists():
        raise FileExistsError(f"replay report already exists: {output.name}")
    first_files = _content_files(first)
    second_files = _content_files(second)
    if set(first_files) != set(second_files):
        missing = sorted(set(first_files) - set(second_files))
        extra = sorted(set(second_files) - set(first_files))
        raise ValueError(
            f"Validation replay artifact sets differ: missing={missing}, extra={extra}"
        )
    rows: list[dict[str, object]] = []
    for relative in sorted(first_files):
        first_hash = sha256_file(first_files[relative])
        second_hash = sha256_file(second_files[relative])
        rows.append(
            {
                "byte_identical": first_hash == second_hash,
                "first_sha256": first_hash,
                "path": relative,
                "second_sha256": second_hash,
            }
        )
    mismatch_count = sum(row["byte_identical"] is False for row in rows)
    payload = {
        "byte_identical": mismatch_count == 0,
        "compared_file_count": len(rows),
        "excluded_run_specific": sorted(_EXCLUDED),
        "mismatch_count": mismatch_count,
        "files": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ReplayReport(mismatch_count == 0, len(rows), mismatch_count, output)


__all__ = ["ReplayReport", "compare_validation_replays"]
