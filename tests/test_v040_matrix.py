# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

import protein_split_audit.cli as cli
import protein_split_audit.experiments.esm_matrix as esm_matrix
from protein_split_audit.evaluation.metrics import EvaluationMetrics
from protein_split_audit.experiments.esm_matrix import (
    EsmCellResult,
    PreparedEmbeddings,
    run_esm_cell,
    run_esm_matrix,
)
from tests.v030_helpers import write_tiny_experiment

PROJECT_ROOT = Path(__file__).parents[1]


def _metrics() -> EvaluationMetrics:
    return EvaluationMetrics(
        label_order=("1.1",),
        macro_f1=1.0,
        balanced_accuracy=1.0,
        accuracy=1.0,
        macro_precision=1.0,
        macro_recall=1.0,
        prediction_coverage=1.0,
        per_class=(),
        confusion_matrix=((1,),),
        no_hit_count=0,
        no_hit_rate=0.0,
        no_hit_correct_count=0,
    )


def test_v040_matrix_runs_exactly_eight_cells_in_frozen_order(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_cell(
        _config_path: Path, model_name: str, split_name: str, *, resume: bool
    ) -> EsmCellResult:
        assert resume is False
        calls.append((model_name, split_name))
        run_dir = tmp_path / f"{split_name}-{model_name}"
        run_dir.mkdir()
        return EsmCellResult(split_name, model_name, "validation", run_dir, _metrics(), "1" * 64)

    config_path = tmp_path / "v040.yaml"
    source = (PROJECT_ROOT / "configs/experiment/v040-validation.yaml").read_text(encoding="utf-8")
    source = source.replace("../../results/runs/v040-validation", "runs")
    config_path.write_text(source, encoding="utf-8")

    result = run_esm_matrix(config_path, cell_runner=fake_cell)

    assert calls == [
        (model, split)
        for split in ("random", "cluster70", "cluster50", "cluster30")
        for model in ("esm2_35m", "esm2_150m")
    ]
    assert len(result.cells) == 8
    assert result.summary_path.is_file()


def _tiny_v040(tmp_path: Path) -> Path:
    tiny = write_tiny_experiment(tmp_path, PROJECT_ROOT)
    mapping = yaml.safe_load(tiny.config.read_text(encoding="utf-8"))
    mapping["experiment_type"] = "esm2_validation"
    mapping.pop("baselines")
    mapping["models"] = [
        {
            "name": "esm2_35m",
            "embedding_config": str(PROJECT_ROOT / "configs/embedding/esm2_35m.yaml"),
        },
        {
            "name": "esm2_150m",
            "embedding_config": str(PROJECT_ROOT / "configs/embedding/esm2_150m.yaml"),
        },
    ]
    mapping["linear_probe_config"] = str(PROJECT_ROOT / "configs/model/esm_linear_probe.yaml")
    mapping["runtime"] = {
        "seed": 42,
        "operating_system": "Darwin",
        "architecture": "arm64",
        "device": "cpu",
        "dtype": "float32",
        "torch_intraop_threads": 8,
        "torch_interop_threads": 1,
        "deterministic_algorithms": True,
    }
    tiny.config.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    return tiny.config


def test_v040_cell_extracts_without_labels_then_evaluates_validation(tmp_path: Path) -> None:
    config_path = _tiny_v040(tmp_path)
    observed_labels: list[tuple[str, ...]] = []

    def provider(*, records, **_kwargs):  # type: ignore[no-untyped-def]
        observed_labels.append(tuple(record.label for record in records))
        matrix = np.asarray(
            [
                [1.0, 0.0] if record.accession in {"T0", "T1", "V0"} else [0.0, 1.0]
                for record in records
            ],
            dtype=np.float32,
        )
        return PreparedEmbeddings(
            matrix=matrix,
            embedding_manifest={"cache_key": "1" * 64},
            embedding_manifest_sha256="2" * 64,
            snapshot_manifest={"snapshot_sha256": "3" * 64},
        )

    result = run_esm_cell(
        config_path,
        "esm2_35m",
        "random",
        embedding_provider=provider,
    )

    assert observed_labels == [("", "", "", "", "", "")]
    assert result.metrics.accuracy == 1.0
    assert (result.run_dir / "predictions.parquet").is_file()
    assert (result.run_dir / "embedding_manifest.json").is_file()
    assert (result.run_dir / "COMPLETE.json").is_file()


def test_v040_cli_dispatches_model_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_run(_path: Path, model: str, split: str) -> EsmCellResult:
        calls.append((model, split))
        return EsmCellResult(split, model, "validation", Path("run"), _metrics(), "1" * 64)

    monkeypatch.setattr(esm_matrix, "run_esm_cell", fake_run)
    result = CliRunner().invoke(
        cli.app,
        [
            "experiment",
            "run",
            "--config",
            str(PROJECT_ROOT / "configs/experiment/v040-validation.yaml"),
            "--split",
            "random",
            "--model",
            "esm2_35m",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("esm2_35m", "random")]


def test_v040_cell_resume_verifies_complete_artifacts(tmp_path: Path) -> None:
    config_path = _tiny_v040(tmp_path)

    def provider(*, records, **_kwargs):  # type: ignore[no-untyped-def]
        matrix = np.asarray(
            [
                [1.0, 0.0] if record.accession in {"T0", "T1", "V0"} else [0.0, 1.0]
                for record in records
            ],
            dtype=np.float32,
        )
        return PreparedEmbeddings(matrix, {"cache_key": "1" * 64}, "2" * 64, {"x": 1})

    original = run_esm_cell(
        config_path,
        "esm2_35m",
        "random",
        embedding_provider=provider,
    )
    resumed = run_esm_cell(
        config_path,
        "esm2_35m",
        "random",
        resume=True,
        embedding_provider=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("resume must not extract embeddings")
        ),
    )

    assert resumed.manifest_sha256 == original.manifest_sha256
    assert resumed.metrics == original.metrics
