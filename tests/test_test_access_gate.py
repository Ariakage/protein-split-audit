# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from protein_split_audit.attestations.test_access import (
    FormalRuntimeIdentity,
    RealTestAccessDenied,
    begin_test_session,
    complete_test_session,
    verify_test_authorization,
    write_test_incident,
)
from protein_split_audit.config import load_experiment_config
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.experiments.test_gate import enforce_test_gate
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE_CONFIG = PROJECT_ROOT / "configs/experiment/v050-test.yaml"
SOURCE_PROTOCOL = PROJECT_ROOT / "docs/protocols/v0.5.0-frozen-test-evaluation.md"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _copy_generation_files(root: Path) -> Path:
    config_path = root / "configs/experiment/v050-test.yaml"
    protocol_path = root / "docs/protocols/v0.5.0-frozen-test-evaluation.md"
    lock_path = root / "uv.lock"
    report_path = root / "docs/audits/v0.5.0-dependency-diff.md"
    for path in (config_path, protocol_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_CONFIG, config_path)
    shutil.copyfile(SOURCE_PROTOCOL, protocol_path)
    shutil.copyfile(PROJECT_ROOT / "uv.lock", lock_path)
    report_path.write_text(
        "<!-- SPDX-License-Identifier: CC-BY-4.0 -->\n\n# Synthetic dependency diff\n",
        encoding="utf-8",
    )
    return config_path


def _logical_method(config: FrozenTestExperimentConfig, root: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for method in config.methods:
        paths = tuple(
            _relative(root, path)
            for path in (method.feature_config, method.model_config_path, method.embedding_config)
            if path is not None
        )
        values.append({"name": method.name, "config_paths": list(paths)})
    return values


def _attestation_mapping(root: Path, generation: str) -> dict[str, object]:
    config_path = root / "configs/experiment/v050-test.yaml"
    config = load_experiment_config(config_path)
    assert isinstance(config, FrozenTestExperimentConfig)

    cohort = config.cohort.model_dump(mode="python")
    for field in ("manifest", "content_manifest", "fasta"):
        cohort[field] = _relative(root, cohort[field])
    splits: list[dict[str, object]] = []
    for split in config.splits:
        item = split.model_dump(mode="python")
        item["manifest"] = _relative(root, split.manifest)
        item["content_manifest"] = _relative(root, split.content_manifest)
        splits.append(item)
    snapshots: list[dict[str, object]] = []
    for snapshot in config.model_snapshots:
        item = snapshot.model_dump(mode="python")
        item["manifest"] = _relative(root, snapshot.manifest)
        snapshots.append(item)
    evidence = [
        {"path": _relative(root, item.path), "sha256": item.sha256}
        for item in config.tracked_evidence
    ]
    return {
        "schema_version": 1,
        "project": "ProteinSplitAudit",
        "release_target": "v0.5.0",
        "attestation_type": "frozen_test_access",
        "protocol": {
            "path": "docs/protocols/v0.5.0-frozen-test-evaluation.md",
            "sha256": sha256_file(root / "docs/protocols/v0.5.0-frozen-test-evaluation.md"),
        },
        "code": {
            "generation_git_commit": generation,
            "generation_git_dirty": False,
            "software_version": "0.5.0",
            "python_version": "3.12.11",
            "configuration": {
                "path": "configs/experiment/v050-test.yaml",
                "sha256": sha256_file(config_path),
            },
            "uv_lock": {"path": "uv.lock", "sha256": sha256_file(root / "uv.lock")},
            "dependency_diff": {
                "path": "docs/audits/v0.5.0-dependency-diff.md",
                "sha256": sha256_file(root / "docs/audits/v0.5.0-dependency-diff.md"),
            },
        },
        "frozen": {
            "cohort": cohort,
            "splits": splits,
            "methods": _logical_method(config, root),
            "tracked_evidence": evidence,
            "model_snapshots": snapshots,
        },
        "experiment": {
            "methods": [item.name for item in config.methods],
            "splits": [item.name for item in config.splits],
            "matrix_cells": config.cell_count,
            "fit_partition": "train",
            "evaluation_partition": "test",
            "validation_policy": "excluded",
            "formal_sessions": list(config.formal_sessions),
            "real_test_access_authorized": True,
        },
        "statistics": {
            "bootstrap": {
                "unit": config.statistics.bootstrap.unit,
                "iterations": config.statistics.bootstrap.iterations,
                "confidence_level": config.statistics.bootstrap.confidence_level,
                "interval_method": config.statistics.bootstrap.interval_method,
                "lower_quantile": config.statistics.bootstrap.lower_quantile,
                "upper_quantile": config.statistics.bootstrap.upper_quantile,
                "seed": config.statistics.bootstrap.seed,
            },
            "within_split_resampling": config.statistics.within_split_resampling,
            "cross_split_resampling": config.statistics.cross_split_resampling,
        },
        "runtime": {
            "operating_system": "Darwin",
            "architecture": "arm64",
            "python_version": "3.12.11",
            "device": "cpu",
            "dtype": "float32",
            "torch_intraop_threads": 8,
            "torch_interop_threads": 1,
            "deterministic_algorithms": True,
            "mmseqs_version": "18-8cc5c",
            "mmseqs_threads": 8,
            "local_files_only": True,
            "network_access": False,
            "dependency_versions": {
                "torch": "2.13.0",
                "transformers": "5.13.1",
                "safetensors": "0.8.0",
                "tokenizers": "0.22.2",
                "huggingface_hub": "1.23.0",
                "accelerate": "1.14.0",
            },
        },
        "approval": {
            "approved_by": "Ariakage",
            "approved_at_utc": "2026-07-16T12:00:00Z",
            "approval_reference": (
                "https://github.com/Ariakage/protein-split-audit/pull/3#issuecomment-5000000000"
            ),
            "author_association": "OWNER",
            "approval_comment_sha256": "c" * 64,
        },
    }


def _expected_hashes(config: FrozenTestExperimentConfig, root: Path) -> dict[Path, str]:
    expected = {
        config.cohort.manifest: config.cohort.file_sha256,
        config.cohort.content_manifest: config.cohort.content_manifest_sha256,
        config.cohort.fasta: config.cohort.fasta_sha256,
    }
    for split in config.splits:
        expected[split.manifest] = split.file_sha256
        expected[split.content_manifest] = split.content_manifest_sha256
    for item in config.tracked_evidence:
        expected[item.path] = item.sha256
    for snapshot in config.model_snapshots:
        expected[snapshot.manifest] = snapshot.manifest_sha256
    for path in (
        root / "configs/experiment/v050-test.yaml",
        root / "docs/protocols/v0.5.0-frozen-test-evaluation.md",
        root / "uv.lock",
        root / "docs/audits/v0.5.0-dependency-diff.md",
    ):
        expected[path] = sha256_file(path)
    return {path.resolve(): digest for path, digest in expected.items()}


def _runtime() -> FormalRuntimeIdentity:
    return FormalRuntimeIdentity(
        software_version="0.5.0",
        python_version="3.12.11",
        operating_system="Darwin",
        architecture="arm64",
        device="cpu",
        dtype="float32",
        torch_intraop_threads=8,
        torch_interop_threads=1,
        deterministic_algorithms=True,
        mmseqs_version="18-8cc5c",
        mmseqs_threads=8,
        local_files_only=True,
        network_access=False,
        dependency_versions={
            "torch": "2.13.0",
            "transformers": "5.13.1",
            "safetensors": "0.8.0",
            "tokenizers": "0.22.2",
            "huggingface_hub": "1.23.0",
            "accelerate": "1.14.0",
        },
    )


def _repository(
    tmp_path: Path,
    *,
    mutate: Callable[[dict[str, object]], None] | None = None,
    extra_b_file: bool = False,
) -> tuple[Path, Path, dict[Path, str], str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    config_path = _copy_generation_files(root)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "generation a")
    generation = _git(root, "rev-parse", "HEAD")
    mapping = _attestation_mapping(root, generation)
    if mutate is not None:
        mutate(mapping)
    attestation = root / "docs/attestations/v0.5.0-test-freeze-r1.yaml"
    attestation.parent.mkdir(parents=True, exist_ok=True)
    attestation.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    if extra_b_file:
        (root / "extra.txt").write_text("not allowed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "attestation b")
    execution = _git(root, "rev-parse", "HEAD")
    config = load_experiment_config(config_path)
    assert isinstance(config, FrozenTestExperimentConfig)
    return root, config_path, _expected_hashes(config, root), generation, execution


def test_valid_test_attestation_returns_an_unforgeable_capability(tmp_path: Path) -> None:
    root, config_path, expected, generation, execution = _repository(tmp_path)
    hashed: list[Path] = []

    def frozen_hash(path: Path) -> str:
        resolved = path.resolve()
        hashed.append(resolved)
        return expected[resolved]

    authorization = verify_test_authorization(
        config_path,
        root,
        runtime=_runtime(),
        frozen_file_hasher=frozen_hash,
        snapshot_verifier=lambda _config: None,
    )

    assert authorization.generation_commit == generation
    assert authorization.execution_commit == execution
    assert authorization.allowed_sessions == ("run-a", "run-b")
    assert authorization.approval_reference.endswith("#issuecomment-5000000000")
    assert hashed


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.__setitem__("project", "Other"),
        lambda value: value["experiment"].__setitem__("real_test_access_authorized", False),
        lambda value: value["approval"].__setitem__("approval_reference", "https://x.test"),
        lambda value: value["code"]["configuration"].__setitem__("sha256", "d" * 64),
        lambda value: value["frozen"]["cohort"].__setitem__("file_sha256", "e" * 64),
        lambda value: value["runtime"].__setitem__("architecture", "x86_64"),
    ),
)
def test_invalid_attestation_denies_before_frozen_inputs(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    root, config_path, _expected, _generation, _execution = _repository(tmp_path, mutate=mutation)

    def forbidden_hash(_path: Path) -> str:
        raise AssertionError("frozen input hashing must not start")

    with pytest.raises(RealTestAccessDenied, match="not authorized"):
        verify_test_authorization(
            config_path,
            root,
            runtime=_runtime(),
            frozen_file_hasher=forbidden_hash,
            snapshot_verifier=lambda _config: None,
        )


def test_dirty_or_non_attestation_b_denies_before_frozen_inputs(tmp_path: Path) -> None:
    root, config_path, _expected, _generation, _execution = _repository(tmp_path, extra_b_file=True)

    with pytest.raises(RealTestAccessDenied, match="not authorized"):
        verify_test_authorization(
            config_path,
            root,
            runtime=_runtime(),
            frozen_file_hasher=lambda _path: pytest.fail("must not hash frozen inputs"),
            snapshot_verifier=lambda _config: None,
        )


def test_missing_attestation_denies_without_hashing_frozen_inputs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config_path = _copy_generation_files(root)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "generation a")

    with pytest.raises(RealTestAccessDenied, match="not authorized"):
        verify_test_authorization(
            config_path,
            root,
            runtime=_runtime(),
            frozen_file_hasher=lambda _path: pytest.fail("must not hash frozen inputs"),
            snapshot_verifier=lambda _config: None,
        )


@pytest.mark.parametrize("mode", ("dirty", "later_head"))
def test_dirty_or_later_head_denies_before_frozen_inputs(tmp_path: Path, mode: str) -> None:
    root, config_path, _expected, _generation, _execution = _repository(tmp_path)
    if mode == "dirty":
        (root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    else:
        (root / "later.txt").write_text("later\n", encoding="utf-8")
        _git(root, "add", "later.txt")
        _git(root, "commit", "-qm", "later commit")

    with pytest.raises(RealTestAccessDenied, match="not authorized"):
        verify_test_authorization(
            config_path,
            root,
            runtime=_runtime(),
            frozen_file_hasher=lambda _path: pytest.fail("must not hash frozen inputs"),
            snapshot_verifier=lambda _config: None,
        )


def test_access_ledger_is_consumed_before_callback_and_cannot_be_reused(tmp_path: Path) -> None:
    root, config_path, expected, _generation, _execution = _repository(tmp_path)
    authorization = verify_test_authorization(
        config_path,
        root,
        runtime=_runtime(),
        frozen_file_hasher=lambda path: expected[path.resolve()],
        snapshot_verifier=lambda _config: None,
    )
    ledger = tmp_path / "ledger"
    observed: list[str] = []

    marker = begin_test_session(
        authorization,
        "run-a",
        ledger,
        before_test_read=lambda: observed.append("callback"),
        now=lambda: datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
    )

    assert observed == ["callback"]
    first = json.loads(marker.read_text(encoding="utf-8").splitlines()[0])
    assert first["test_session_status"] == "consumed"
    assert first["test_access_started_at_utc"] == "2026-07-16T12:01:00Z"
    with pytest.raises(RealTestAccessDenied, match="already consumed"):
        begin_test_session(
            authorization,
            "run-a",
            ledger,
            before_test_read=lambda: pytest.fail("callback must not run twice"),
        )

    complete_test_session(authorization, "run-a", ledger, "f" * 64)
    events = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["test_access_started", "session_completed"]


def test_incident_report_is_local_sanitized_and_immutable(tmp_path: Path) -> None:
    root, config_path, expected, _generation, _execution = _repository(tmp_path)
    authorization = verify_test_authorization(
        config_path,
        root,
        runtime=_runtime(),
        frozen_file_hasher=lambda path: expected[path.resolve()],
        snapshot_verifier=lambda _config: None,
    )
    incident_root = tmp_path / "incidents"
    path = write_test_incident(
        authorization,
        "run-b",
        incident_root,
        failure_stage="prediction",
        exception_class="RuntimeError",
        partial_results_viewed=False,
        last_verified_hashes={"config": "a" * 64},
        test_access_started_at_utc="2026-07-16T12:01:00Z",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["session_id"] == "run-b"
    assert "sequence" not in path.read_text(encoding="utf-8").lower()
    with pytest.raises(FileExistsError):
        write_test_incident(
            authorization,
            "run-b",
            incident_root,
            failure_stage="prediction",
            exception_class="RuntimeError",
            partial_results_viewed=False,
            last_verified_hashes={"config": "a" * 64},
            test_access_started_at_utc="2026-07-16T12:01:00Z",
        )


def test_legacy_finalize_gate_cannot_accept_a_v050_attestation(tmp_path: Path) -> None:
    attestation = tmp_path / "v050.yaml"
    attestation.write_text(
        """\
schema_version: 1
project: ProteinSplitAudit
release_target: v0.5.0
attestation_type: frozen_test_access
experiment:
  real_test_access_authorized: true
""",
        encoding="utf-8",
    )

    with pytest.raises(RealTestAccessDenied, match="not authorized"):
        enforce_test_gate(
            attestation,
            before_real_input=lambda: pytest.fail("legacy gate opened v0.5 input"),
        )
