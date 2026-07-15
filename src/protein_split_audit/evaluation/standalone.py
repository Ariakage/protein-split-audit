# SPDX-License-Identifier: Apache-2.0

"""Validation-only verification for a completed evaluation run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from protein_split_audit.provenance import sha256_file


@dataclass(frozen=True, slots=True)
class VerifiedEvaluationRun:
    """A byte-verified completed Validation run."""

    run_dir: Path
    evaluation_split: str
    artifact_count: int
    metrics_path: Path


def verify_evaluation_run(run_dir: Path) -> VerifiedEvaluationRun:
    """Verify a completed Validation report without opening Test inputs."""

    complete_path = run_dir / "COMPLETE.json"
    try:
        complete = json.loads(complete_path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("evaluation run has no valid COMPLETE.json") from error
    if complete.get("evaluation_split") != "validation":
        raise ValueError("v0.3 evaluate run is Validation-only")
    artifact_hashes = complete.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise ValueError("evaluation run has no valid artifact index")
    current_files = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path != complete_path
    }
    if current_files != set(artifact_hashes):
        raise ValueError("evaluation run artifact set mismatch")
    for relative, expected in sorted(artifact_hashes.items()):
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("evaluation run artifact index is malformed")
        if sha256_file(run_dir / relative) != expected:
            raise ValueError(f"evaluation run artifact hash mismatch: {relative}")
    metrics_path = run_dir / "metrics.json"
    json.loads(metrics_path.read_bytes())
    return VerifiedEvaluationRun(run_dir, "validation", len(artifact_hashes), metrics_path)


__all__ = ["VerifiedEvaluationRun", "verify_evaluation_run"]
