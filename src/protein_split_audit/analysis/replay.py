# SPDX-License-Identifier: Apache-2.0

"""Exact deterministic replay comparison for two formal analysis sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from protein_split_audit.analysis.aggregate import json_bytes
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes, sha256_file
from protein_split_audit.publication import publish_bundle

_REPLAY_TOKEN = object()
_EXCLUDED = {
    "run_provenance.json": "run-specific timestamp and local execution details",
}


class AnalysisReplayError(RuntimeError):
    """Raised when two formal analysis sessions are not exact replays."""


@dataclass(frozen=True, slots=True)
class VerifiedAnalysisReplay:
    """Opaque authority to aggregate one byte-reproduced analysis run."""

    run_a_inventory_sha256: str
    run_b_inventory_sha256: str
    compared_files: tuple[str, ...]
    _token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class AnalysisReplayResult:
    """Written replay report and its opaque aggregate capability."""

    report_path: Path
    report_sha256: str
    authorization: VerifiedAnalysisReplay


def _inventory(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise AnalysisReplayError("analysis replay input directory is missing")
    output = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).as_posix() not in _EXCLUDED
    }
    if not output:
        raise AnalysisReplayError("analysis replay has no deterministic artifacts")
    return output


def _inventory_sha256(inventory: dict[str, str]) -> str:
    return sha256_bytes(serialize_canonical_json(inventory))


def deterministic_inventory_sha256(root: Path) -> str:
    """Return the canonical hash of replay-compared files in one run."""

    return _inventory_sha256(_inventory(root.resolve()))


def compare_analysis_replays(
    run_a: Path,
    run_b: Path,
    output: Path,
) -> AnalysisReplayResult:
    """Require byte identity for every deterministic artifact before reporting."""

    first = _inventory(run_a.resolve())
    second = _inventory(run_b.resolve())
    if first != second:
        raise AnalysisReplayError("analysis replay contains a deterministic mismatch")
    first_hash = _inventory_sha256(first)
    second_hash = _inventory_sha256(second)
    report = {
        "aggregate_authorized": True,
        "compared_file_count": len(first),
        "compared_files": tuple(first),
        "deterministic_mismatch_count": 0,
        "excluded_files": _EXCLUDED,
        "run_a_inventory_sha256": first_hash,
        "run_b_inventory_sha256": second_hash,
        "schema_version": 1,
    }
    content = json_bytes(report)
    destination = output.resolve()
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing analysis replay report")
    publish_bundle({destination: content})
    capability = VerifiedAnalysisReplay(first_hash, second_hash, tuple(first), _REPLAY_TOKEN)
    return AnalysisReplayResult(
        report_path=destination,
        report_sha256=sha256_bytes(content),
        authorization=capability,
    )


def require_verified_analysis_replay(value: object) -> None:
    """Reject a manually constructed or failed replay result."""

    if not isinstance(value, VerifiedAnalysisReplay) or value._token is not _REPLAY_TOKEN:
        raise AnalysisReplayError("analysis aggregate is not authorized by an exact replay")


__all__ = [
    "AnalysisReplayError",
    "AnalysisReplayResult",
    "VerifiedAnalysisReplay",
    "compare_analysis_replays",
    "deterministic_inventory_sha256",
    "require_verified_analysis_replay",
]
