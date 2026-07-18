# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protein_split_audit.config import load_experiment_config
from protein_split_audit.evaluation.test_matrix import frozen_test_cells
from protein_split_audit.experiments.replay import (
    compare_test_replays,
    require_verified_replay,
)
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]


def _write_json(path: Path, mapping: dict[str, object]) -> None:
    path.write_text(json.dumps(mapping, sort_keys=True) + "\n", encoding="utf-8")


def _formal_pair(
    root: Path,
    *,
    attestation_sha256: str = "a" * 64,
) -> tuple[Path, Path]:
    loaded = load_experiment_config(PROJECT_ROOT / "configs/experiment/v050-test.yaml")
    assert isinstance(loaded, FrozenTestExperimentConfig)
    cells = frozen_test_cells(loaded)
    first = root / "run-a"
    second = root / "run-b"
    for session_root, session, elapsed in (
        (first, "run-a", 1.0),
        (second, "run-b", 2.0),
    ):
        for cell in cells:
            directory = session_root / cell.cell_id
            directory.mkdir(parents=True)
            deterministic = {
                "config_resolved.yaml": b"name: frozen\n",
                "input_hashes.json": b'{"cohort":"a"}\n',
                "model_manifest.json": b'{"fit_partitions":["train"]}\n',
                "prediction_manifest.json": b'{"status":"complete"}\n',
                "predictions_unlabeled.parquet": b"unlabeled-predictions",
                "predictions.parquet": b"joined-predictions",
                "metrics.json": b'{"macro_f1":0.5}\n',
                "per_class_metrics.csv": b"label,support,f1\n2.7,1,0.5\n",
                "confusion_matrix.csv": b"true_label,2.7\n2.7,1\n",
                "confidence_intervals.json": b'{"valid_iterations":2000}\n',
                "environment.json": b'{"architecture":"arm64","operating_system":"Darwin"}\n',
            }
            for name, content in deterministic.items():
                (directory / name).write_bytes(content)
            _write_json(directory / "resource_usage.json", {"elapsed_seconds": elapsed})
            (directory / "run.log").write_text(f"session={session}\n", encoding="utf-8")
            artifacts = {
                path.name: sha256_file(path)
                for path in sorted(directory.iterdir())
                if path.is_file()
            }
            _write_json(
                directory / "COMPLETE.json",
                {
                    "artifact_sha256": artifacts,
                    "attestation_sha256": attestation_sha256,
                    "cell_id": cell.cell_id,
                    "evaluation_split": "test",
                    "execution_commit": "b" * 40,
                    "fit_partitions": ["train"],
                    "method": cell.method_name,
                    "prediction_partitions": ["test"],
                    "session": session,
                    "split": cell.split_name,
                    "validation_rows_accessed": 0,
                },
            )
        _write_json(session_root / "statistics.json", {"bootstrap_iterations": 2000})
        _write_json(
            session_root / "matrix_summary.json",
            {
                "attestation_sha256": attestation_sha256,
                "cell_count": 28,
                "evaluation_split": "test",
                "execution_commit": "b" * 40,
                "session": session,
            },
        )
    ledger = root / "access-ledger"
    ledger.mkdir()
    for session, session_root in (("run-a", first), ("run-b", second)):
        summary_hash = sha256_file(session_root / "matrix_summary.json")
        lines = (
            {
                "attestation_sha256": attestation_sha256,
                "event": "test_access_started",
                "execution_commit": "b" * 40,
                "session_id": session,
                "test_access_started_at_utc": (
                    "2026-07-16T01:00:00Z" if session == "run-a" else "2026-07-16T02:00:00Z"
                ),
                "test_session_status": "consumed",
            },
            {
                "event": "session_completed",
                "result_sha256": summary_hash,
                "session_id": session,
                "test_session_status": "completed",
            },
        )
        (ledger / f"{session}.jsonl").write_text(
            "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines),
            encoding="utf-8",
        )
    return first, second


def test_exact_formal_replay_returns_opaque_release_capability(tmp_path: Path) -> None:
    first, second = _formal_pair(tmp_path)

    report = compare_test_replays(first, second, tmp_path / "replay.json")

    assert report.byte_identical is True
    assert report.release_eligible is True
    assert report.replay_difference == 0
    assert report.deterministic_mismatch_count == 0
    assert report.capability is not None
    require_verified_replay(report.capability)


@pytest.mark.parametrize(
    ("relative", "replacement", "category"),
    [
        ("metrics.json", b'{"macro_f1":0.6}\n', "metric"),
        ("predictions.parquet", b"changed", "prediction"),
        ("confidence_intervals.json", b'{"valid_iterations":1999}\n', "bootstrap"),
    ],
)
def test_one_deterministic_mutation_blocks_release(
    tmp_path: Path,
    relative: str,
    replacement: bytes,
    category: str,
) -> None:
    first, second = _formal_pair(tmp_path)
    cell = sorted(path for path in second.iterdir() if path.is_dir())[0]
    (cell / relative).write_bytes(replacement)
    complete = json.loads((cell / "COMPLETE.json").read_bytes())
    complete["artifact_sha256"][relative] = sha256_file(cell / relative)
    _write_json(cell / "COMPLETE.json", complete)

    report = compare_test_replays(first, second, tmp_path / "changed.json")

    assert report.byte_identical is False
    assert report.release_eligible is False
    assert report.replay_difference > 0
    assert report.capability is None
    if category == "metric":
        assert report.metric_difference > 0
    elif category == "prediction":
        assert report.prediction_disagreement_count > 0
    else:
        assert report.bootstrap_difference > 0


def test_extra_deterministic_file_and_missing_cell_block_release(tmp_path: Path) -> None:
    first, second = _formal_pair(tmp_path)
    cell = sorted(path for path in second.iterdir() if path.is_dir())[0]
    (cell / "unexpected.bin").write_bytes(b"unexpected")

    report = compare_test_replays(first, second, tmp_path / "extra.json")

    assert report.release_eligible is False
    assert report.mismatch_count > 0
