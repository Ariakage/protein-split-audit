# SPDX-License-Identifier: Apache-2.0

"""Deterministic content comparison for two Validation matrix replays."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

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


_TEST_REPLAY_TOKEN = object()
_TEST_METHODS = (
    "majority",
    "length-logistic",
    "aac-logistic",
    "kmer3-logistic",
    "nearest-homolog",
    "esm2-35m",
    "esm2-150m",
)
_TEST_SPLITS = ("random", "cluster70", "cluster50", "cluster30")
_TEST_CELL_IDS = tuple(
    f"v050-test__{method}__{split}" for method in _TEST_METHODS for split in _TEST_SPLITS
)
_TEST_REQUIRED_CELL_FILES = frozenset(
    {
        "COMPLETE.json",
        "confidence_intervals.json",
        "config_resolved.yaml",
        "confusion_matrix.csv",
        "environment.json",
        "input_hashes.json",
        "metrics.json",
        "model_manifest.json",
        "per_class_metrics.csv",
        "prediction_manifest.json",
        "predictions.parquet",
        "predictions_unlabeled.parquet",
        "resource_usage.json",
        "run.log",
    }
)
_TEST_EXCLUDED_RUN_SPECIFIC = (
    "resource_usage.json: elapsed time and peak memory",
    "run.log: session-local execution log",
    "access-ledger/*.jsonl: UTC access timestamps and session identifier",
    "COMPLETE.json: hashes of the two run-specific files above",
    "feature_cache/manifest.json and embedding_cache/manifest.json: session namespace only",
    "matrix_summary.json: session identifier and per-session completion hashes",
)


@dataclass(frozen=True, slots=True)
class VerifiedReplayCapability:
    """Opaque authority issued only by a passing exact Test replay."""

    first_root: Path
    second_root: Path
    first_root_sha256: str
    second_root_sha256: str
    report_path: Path
    report_sha256: str
    attestation_sha256: str
    execution_commit: str
    _token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TestReplayReport:
    """Exact formal Test replay result and optional aggregate authority."""

    byte_identical: bool
    release_eligible: bool
    replay_difference: int
    compared_file_count: int
    mismatch_count: int
    deterministic_mismatch_count: int
    prediction_disagreement_count: int
    metric_difference: int
    bootstrap_difference: int
    mismatches: tuple[str, ...]
    excluded_run_specific: tuple[str, ...]
    output_path: Path
    capability: VerifiedReplayCapability | None


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


def _replace_session_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "<formal-session>" if str(key) == "session" else _replace_session_fields(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_session_fields(item) for item in value]
    return value


def _test_json_digest(relative: str, path: Path) -> str:
    try:
        value = json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"formal replay JSON is invalid: {relative}") from error
    if not isinstance(value, dict):
        raise ValueError(f"formal replay JSON must be a mapping: {relative}")
    name = Path(relative).name
    normalized: object = value
    if name == "environment.json":
        normalized = _without_run_fields(value)
    elif relative.endswith(("feature_cache/manifest.json", "embedding_cache/manifest.json")):
        normalized = _replace_session_fields(value)
    elif name == "COMPLETE.json":
        cleaned = dict(value)
        cleaned["session"] = "<formal-session>"
        artifact_hashes = cleaned.get("artifact_sha256")
        if isinstance(artifact_hashes, dict):
            cleaned["artifact_sha256"] = {
                str(key): item
                for key, item in artifact_hashes.items()
                if Path(str(key)).name not in {"resource_usage.json", "run.log"}
                and str(key) not in {"feature_cache/manifest.json", "embedding_cache/manifest.json"}
            }
        normalized = cleaned
    elif name == "matrix_summary.json":
        cleaned = dict(value)
        cleaned["session"] = "<formal-session>"
        cells = cleaned.get("cells")
        if isinstance(cells, list):
            cleaned["cells"] = [
                {str(key): item for key, item in cell.items() if str(key) != "manifest_sha256"}
                if isinstance(cell, dict)
                else cell
                for cell in cells
            ]
        normalized = cleaned
    if not isinstance(normalized, dict):
        raise AssertionError("normalized formal replay JSON must remain a mapping")
    return sha256_bytes(serialize_canonical_json(normalized))


def _test_artifact_digest(relative: str, path: Path) -> str | None:
    name = Path(relative).name
    if name in {"resource_usage.json", "run.log"}:
        return None
    if path.suffix == ".json":
        return _test_json_digest(relative, path)
    return sha256_file(path)


def _approved_test_relative(relative: str) -> bool:
    parts = Path(relative).parts
    if len(parts) == 1:
        return parts[0] in {"matrix_summary.json", "statistics.json"}
    if len(parts) < 2 or parts[0] not in _TEST_CELL_IDS:
        return False
    nested = Path(*parts[1:]).as_posix()
    if nested in _TEST_REQUIRED_CELL_FILES or nested in {
        "model.joblib",
        "nearest_homolog.parquet",
    }:
        return True
    return nested in {
        "embedding_cache/embeddings.npy",
        "embedding_cache/index.parquet",
        "embedding_cache/manifest.json",
        "feature_cache/data.npy",
        "feature_cache/index.parquet",
        "feature_cache/indices.npy",
        "feature_cache/indptr.npy",
        "feature_cache/manifest.json",
        "feature_cache/matrix.npy",
    }


def _formal_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ValueError("formal Test replay directory is missing")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _directory_sha256(root: Path) -> str:
    inventory: dict[str, object] = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return sha256_bytes(serialize_canonical_json(inventory))


def _validate_session(
    root: Path,
    expected_session: Literal["run-a", "run-b"],
) -> tuple[list[str], str, str]:
    mismatches: list[str] = []
    if root.name != expected_session:
        mismatches.append(f"session-root:{expected_session}")
    cell_names = tuple(sorted(path.name for path in root.iterdir() if path.is_dir()))
    if set(cell_names) != set(_TEST_CELL_IDS):
        mismatches.append(f"cell-set:{expected_session}")
    for cell_id in _TEST_CELL_IDS:
        cell = root / cell_id
        if not cell.is_dir():
            continue
        present = {path.relative_to(cell).as_posix() for path in cell.rglob("*") if path.is_file()}
        missing = _TEST_REQUIRED_CELL_FILES - present
        if missing:
            mismatches.append(f"required-files:{expected_session}:{cell_id}")
        complete_path = cell / "COMPLETE.json"
        if not complete_path.is_file():
            continue
        try:
            complete = json.loads(complete_path.read_bytes())
        except (json.JSONDecodeError, OSError):
            mismatches.append(f"complete-json:{expected_session}:{cell_id}")
            continue
        artifact_hashes = complete.get("artifact_sha256")
        actual = {
            path.relative_to(cell).as_posix(): sha256_file(path)
            for path in sorted(cell.rglob("*"))
            if path.is_file() and path != complete_path
        }
        if not isinstance(artifact_hashes, dict) or artifact_hashes != actual:
            mismatches.append(f"complete-hashes:{expected_session}:{cell_id}")
        if (
            complete.get("cell_id") != cell_id
            or complete.get("session") != expected_session
            or complete.get("evaluation_split") != "test"
            or complete.get("fit_partitions") != ["train"]
            or complete.get("prediction_partitions") != ["test"]
            or complete.get("validation_rows_accessed") != 0
        ):
            mismatches.append(f"complete-identity:{expected_session}:{cell_id}")
    summary_path = root / "matrix_summary.json"
    statistics_path = root / "statistics.json"
    if not summary_path.is_file() or not statistics_path.is_file():
        mismatches.append(f"session-summary:{expected_session}")
        return mismatches, "", ""
    try:
        summary = json.loads(summary_path.read_bytes())
    except (json.JSONDecodeError, OSError):
        mismatches.append(f"summary-json:{expected_session}")
        return mismatches, "", ""
    if (
        summary.get("session") != expected_session
        or summary.get("cell_count") != 28
        or summary.get("evaluation_split") != "test"
    ):
        mismatches.append(f"summary-identity:{expected_session}")
    attestation = summary.get("attestation_sha256")
    execution = summary.get("execution_commit")
    if not isinstance(attestation, str) or len(attestation) != 64:
        mismatches.append(f"summary-attestation:{expected_session}")
        attestation = ""
    if not isinstance(execution, str) or len(execution) != 40:
        mismatches.append(f"summary-execution:{expected_session}")
        execution = ""
    return mismatches, attestation, execution


def _validate_access_ledger(first: Path, second: Path) -> list[str]:
    mismatches: list[str] = []
    if first.parent != second.parent:
        return ["access-ledger:session-roots-have-different-parents"]
    timestamps: list[datetime] = []
    for session, root in (("run-a", first), ("run-b", second)):
        path = first.parent / "access-ledger" / f"{session}.jsonl"
        try:
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        except (OSError, json.JSONDecodeError):
            mismatches.append(f"access-ledger:{session}:invalid")
            continue
        if len(events) != 2:
            mismatches.append(f"access-ledger:{session}:event-count")
            continue
        started, completed = events
        if (
            started.get("event") != "test_access_started"
            or started.get("session_id") != session
            or started.get("test_session_status") != "consumed"
            or completed.get("event") != "session_completed"
            or completed.get("session_id") != session
            or completed.get("test_session_status") != "completed"
            or completed.get("result_sha256") != sha256_file(root / "matrix_summary.json")
        ):
            mismatches.append(f"access-ledger:{session}:identity")
        timestamp = started.get("test_access_started_at_utc")
        if not isinstance(timestamp, str):
            mismatches.append(f"access-ledger:{session}:timestamp")
        else:
            try:
                timestamps.append(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
            except ValueError:
                mismatches.append(f"access-ledger:{session}:timestamp")
    if len(timestamps) == 2 and timestamps[0] >= timestamps[1]:
        mismatches.append("access-ledger:session-order")
    return mismatches


def require_verified_replay(capability: VerifiedReplayCapability) -> None:
    """Reject manually authored replay reports or forged capability values."""

    if (
        not isinstance(capability, VerifiedReplayCapability)
        or capability._token is not _TEST_REPLAY_TOKEN
    ):
        raise ValueError("formal Test replay is not verified")


def verify_replay_capability_files(capability: VerifiedReplayCapability) -> None:
    """Rehash both formal roots and the report before aggregate creation."""

    require_verified_replay(capability)
    if (
        _directory_sha256(capability.first_root) != capability.first_root_sha256
        or _directory_sha256(capability.second_root) != capability.second_root_sha256
        or sha256_file(capability.report_path) != capability.report_sha256
    ):
        raise ValueError("formal Test replay files changed after verification")


def compare_test_replays(first: Path, second: Path, output: Path) -> TestReplayReport:
    """Compare exact same-platform Test sessions and issue aggregate authority on success."""

    if output.exists():
        raise FileExistsError(f"Test replay report already exists: {output.name}")
    resolved_output = output.resolve()
    if resolved_output.is_relative_to(first.resolve()) or resolved_output.is_relative_to(
        second.resolve()
    ):
        raise ValueError("Test replay report must be outside both session roots")
    first_files = _formal_files(first)
    second_files = _formal_files(second)
    mismatches: list[str] = []
    first_validation, first_attestation, first_execution = _validate_session(first, "run-a")
    second_validation, second_attestation, second_execution = _validate_session(second, "run-b")
    mismatches.extend(first_validation)
    mismatches.extend(second_validation)
    mismatches.extend(_validate_access_ledger(first, second))
    if first_attestation != second_attestation:
        mismatches.append("attestation-identity")
    if first_execution != second_execution:
        mismatches.append("execution-identity")

    unapproved = sorted(
        relative
        for relative in set(first_files) | set(second_files)
        if not _approved_test_relative(relative)
    )
    mismatches.extend(f"unapproved-file:{relative}" for relative in unapproved)
    missing = sorted(set(first_files) - set(second_files))
    extra = sorted(set(second_files) - set(first_files))
    mismatches.extend(f"artifact-set:missing:{relative}" for relative in missing)
    mismatches.extend(f"artifact-set:extra:{relative}" for relative in extra)

    rows: list[dict[str, object]] = []
    prediction_difference = 0
    metric_difference = 0
    bootstrap_difference = 0
    for relative in sorted(set(first_files) & set(second_files)):
        first_hash = _test_artifact_digest(relative, first_files[relative])
        second_hash = _test_artifact_digest(relative, second_files[relative])
        if first_hash is None or second_hash is None:
            continue
        identical = first_hash == second_hash
        rows.append(
            {
                "byte_identical": identical,
                "first_sha256": first_hash,
                "path": relative,
                "second_sha256": second_hash,
            }
        )
        if not identical:
            mismatches.append(f"content:{relative}")
            name = Path(relative).name
            if "prediction" in name:
                prediction_difference += 1
            if name in {"metrics.json", "per_class_metrics.csv", "confusion_matrix.csv"}:
                metric_difference += 1
            if name in {"confidence_intervals.json", "statistics.json"}:
                bootstrap_difference += 1
    unique_mismatches = tuple(dict.fromkeys(mismatches))
    deterministic_mismatch_count = len(unique_mismatches)
    byte_identical = deterministic_mismatch_count == 0
    payload: dict[str, object] = {
        "bootstrap_difference": bootstrap_difference,
        "byte_identical": byte_identical,
        "compared_file_count": len(rows),
        "deterministic_mismatch_count": deterministic_mismatch_count,
        "excluded_run_specific": list(_TEST_EXCLUDED_RUN_SPECIFIC),
        "files": rows,
        "metric_difference": metric_difference,
        "mismatch_count": deterministic_mismatch_count,
        "mismatches": list(unique_mismatches),
        "prediction_disagreement_count": prediction_difference,
        "release_eligible": byte_identical,
        "replay_difference": deterministic_mismatch_count,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    capability = (
        VerifiedReplayCapability(
            first_root=first.resolve(),
            second_root=second.resolve(),
            first_root_sha256=_directory_sha256(first),
            second_root_sha256=_directory_sha256(second),
            report_path=output.resolve(),
            report_sha256=sha256_file(output),
            attestation_sha256=first_attestation,
            execution_commit=first_execution,
            _token=_TEST_REPLAY_TOKEN,
        )
        if byte_identical
        else None
    )
    return TestReplayReport(
        byte_identical=byte_identical,
        release_eligible=byte_identical,
        replay_difference=deterministic_mismatch_count,
        compared_file_count=len(rows),
        mismatch_count=deterministic_mismatch_count,
        deterministic_mismatch_count=deterministic_mismatch_count,
        prediction_disagreement_count=prediction_difference,
        metric_difference=metric_difference,
        bootstrap_difference=bootstrap_difference,
        mismatches=unique_mismatches,
        excluded_run_specific=_TEST_EXCLUDED_RUN_SPECIFIC,
        output_path=output,
        capability=capability,
    )


__all__ = [
    "EsmReplayReport",
    "ReplayReport",
    "TestReplayReport",
    "VerifiedReplayCapability",
    "compare_esm_replays",
    "compare_test_replays",
    "compare_validation_replays",
    "require_verified_replay",
    "verify_replay_capability_files",
]
