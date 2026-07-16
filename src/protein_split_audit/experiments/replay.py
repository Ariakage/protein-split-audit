# SPDX-License-Identifier: Apache-2.0

"""Deterministic content comparison for two Validation matrix replays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes, sha256_file

_EXCLUDED = frozenset({"COMPLETE.json", "environment.json", "resource_usage.json", "run.log"})
_ESM_EXCLUDED = frozenset({"COMPLETE.json", "resource_usage.json", "run.log"})
_RUN_SPECIFIC_ENVIRONMENT_FIELDS = frozenset(
    {
        "downloaded_at_utc",
        "finished_at_utc",
        "generated_at_utc",
        "host",
        "hostname",
        "run_host",
        "started_at_utc",
        "timestamp",
    }
)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """Summary of deterministic artifact equality."""

    byte_identical: bool
    compared_file_count: int
    mismatch_count: int
    output_path: Path


@dataclass(frozen=True, slots=True)
class EsmReplayReport:
    """Exact formal replay status or non-gating cross-platform diagnostics."""

    byte_identical: bool
    release_eligible: bool
    replay_difference: int
    compared_file_count: int
    output_path: Path


def _content_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ValueError("Validation replay directory is missing")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in _EXCLUDED
    }


def _esm_content_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ValueError("ESM replay directory is missing")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in _ESM_EXCLUDED
    }


def _without_run_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _without_run_fields(item)
            for key, item in value.items()
            if str(key) not in _RUN_SPECIFIC_ENVIRONMENT_FIELDS
        }
    if isinstance(value, list):
        return [_without_run_fields(item) for item in value]
    return value


def _esm_artifact_sha256(relative: str, path: Path) -> str:
    if Path(relative).name != "environment.json":
        return sha256_file(path)
    try:
        mapping = json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError("ESM environment identity is not valid JSON") from error
    if not isinstance(mapping, dict):
        raise ValueError("ESM environment identity must be a mapping")
    cleaned = _without_run_fields(mapping)
    if not isinstance(cleaned, dict):
        raise AssertionError("cleaned ESM environment identity must remain a mapping")
    return sha256_bytes(serialize_canonical_json(cleaned))


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


def _numeric_diagnostics(
    first_files: dict[str, Path], second_files: dict[str, Path]
) -> dict[str, object]:
    maximum_absolute = 0.0
    maximum_relative = 0.0
    outside = 0
    for relative in sorted(first_files):
        if not relative.endswith(".npy"):
            continue
        first = np.load(first_files[relative], allow_pickle=False)
        second = np.load(second_files[relative], allow_pickle=False)
        if first.shape != second.shape:
            outside += max(first.size, second.size)
            continue
        absolute = np.abs(first.astype(np.float64) - second.astype(np.float64))
        denominator = np.maximum(np.abs(first.astype(np.float64)), np.finfo(np.float64).tiny)
        relative_difference = absolute / denominator
        maximum_absolute = max(maximum_absolute, float(absolute.max(initial=0.0)))
        maximum_relative = max(maximum_relative, float(relative_difference.max(initial=0.0)))
        outside += int(np.count_nonzero(~np.isclose(first, second, rtol=1e-5, atol=1e-6)))
    prediction_disagreement_count = sum(
        sha256_file(first_files[path]) != sha256_file(second_files[path])
        for path in first_files
        if "prediction" in Path(path).name
    )
    metric_difference = sum(
        sha256_file(first_files[path]) != sha256_file(second_files[path])
        for path in first_files
        if Path(path).name == "metrics.json"
    )
    return {
        "max_absolute_difference": maximum_absolute,
        "max_relative_difference": maximum_relative,
        "metric_difference": metric_difference,
        "number_of_values_outside_tolerance": outside,
        "prediction_disagreement_count": prediction_disagreement_count,
    }


def compare_esm_replays(
    first: Path,
    second: Path,
    output: Path,
    *,
    cross_platform: bool = False,
) -> EsmReplayReport:
    """Compare ESM artifacts exactly; optionally add non-gating numeric diagnostics."""

    if output.exists():
        raise FileExistsError(f"ESM replay report already exists: {output.name}")
    first_files = _esm_content_files(first)
    second_files = _esm_content_files(second)
    if set(first_files) != set(second_files):
        raise ValueError("ESM replay artifact sets differ")
    rows: list[dict[str, object]] = []
    for relative in sorted(first_files):
        first_hash = _esm_artifact_sha256(relative, first_files[relative])
        second_hash = _esm_artifact_sha256(relative, second_files[relative])
        rows.append(
            {
                "byte_identical": first_hash == second_hash,
                "first_sha256": first_hash,
                "path": relative,
                "second_sha256": second_hash,
            }
        )
    mismatch_count = sum(row["byte_identical"] is False for row in rows)
    byte_identical = mismatch_count == 0
    payload: dict[str, object] = {
        "byte_identical": byte_identical,
        "compared_file_count": len(rows),
        "cross_platform": cross_platform,
        "files": rows,
        "release_eligible": byte_identical and not cross_platform,
        "replay_difference": mismatch_count,
    }
    if cross_platform:
        payload.update(
            {
                "atol": 1e-6,
                "diagnostics": _numeric_diagnostics(first_files, second_files),
                "release_eligible": False,
                "rtol": 1e-5,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return EsmReplayReport(
        byte_identical,
        bool(payload["release_eligible"]),
        mismatch_count,
        len(rows),
        output,
    )


__all__ = [
    "EsmReplayReport",
    "ReplayReport",
    "compare_esm_replays",
    "compare_validation_replays",
]
