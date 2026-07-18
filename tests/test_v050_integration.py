# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from protein_split_audit.config import load_experiment_config
from protein_split_audit.evaluation.metrics import EvaluationMetrics, PerClassMetrics
from protein_split_audit.evaluation.test_inputs import FrozenTestBundle
from protein_split_audit.evaluation.test_matrix import (
    TestCellResult as FormalCellResult,
)
from protein_split_audit.evaluation.test_matrix import (
    _run_test_session_from_config,
    frozen_test_cells,
)
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from tests.test_test_partition_isolation import _authorization
from tests.test_v050_train_only_fit import _bundle

PROJECT_ROOT = Path(__file__).parents[1]


def test_every_cell_is_bound_to_one_frozen_method_and_split() -> None:
    config = load_experiment_config(PROJECT_ROOT / "configs/experiment/v050-test.yaml")
    assert isinstance(config, FrozenTestExperimentConfig)

    cells = frozen_test_cells(config)

    assert {(cell.method_name, cell.split_name) for cell in cells} == {
        (method.name, split.name) for method in config.methods for split in config.splits
    }
    assert all(cell.method == config.methods[index // 4] for index, cell in enumerate(cells))
    assert all(cell.split == config.splits[index % 4] for index, cell in enumerate(cells))


def _metrics() -> EvaluationMetrics:
    labels = ("2.7", "3.1", "1.1", "2.1", "4.1")
    return EvaluationMetrics(
        label_order=labels,
        macro_f1=1.0,
        balanced_accuracy=1.0,
        accuracy=1.0,
        macro_precision=1.0,
        macro_recall=1.0,
        prediction_coverage=1.0,
        per_class=tuple(PerClassMetrics(label, 1, 1.0, 1.0, 1.0) for label in labels),
        confusion_matrix=tuple(
            tuple(1 if row == column else 0 for column in range(5)) for row in range(5)
        ),
        no_hit_count=0,
        no_hit_rate=0.0,
        no_hit_correct_count=0,
    )


def test_synthetic_session_consumes_once_and_completes_exactly_28_cells(
    tmp_path: Path,
) -> None:
    loaded = load_experiment_config(PROJECT_ROOT / "configs/experiment/v050-test.yaml")
    assert isinstance(loaded, FrozenTestExperimentConfig)
    config = loaded.model_copy(
        update={"outputs": loaded.outputs.model_copy(update={"root": tmp_path / "formal"})}
    )
    base = _bundle()

    def bundle_loader(
        _config: FrozenTestExperimentConfig,
        split_name: str,
        _authorization_value: object,
    ) -> FrozenTestBundle:
        return FrozenTestBundle(
            records=base.records,
            train_labels=base.train_labels,
            label_order=base.label_order,
            input_hashes=base.input_hashes,
            split_name=split_name,  # type: ignore[arg-type]
            _cohort_manifest=base._cohort_manifest,
        )

    def cell_runner(
        _config_path: Path,
        _config: FrozenTestExperimentConfig,
        cell: object,
        _bundle_value: FrozenTestBundle,
        _authorization_value: object,
        session: str,
    ) -> FormalCellResult:
        from protein_split_audit.evaluation.test_matrix import FrozenTestCell

        assert isinstance(cell, FrozenTestCell)
        run_dir = config.outputs.root / session / cell.cell_id
        run_dir.mkdir(parents=True)
        return FormalCellResult(
            cell.cell_id,
            cell.method_name,
            cell.split_name,
            run_dir,
            _metrics(),
            "a" * 64,
        )

    def statistics_writer(
        _results: object,
        _bundles: object,
        _config: object,
        root: Path,
    ) -> Path:
        path = root / "statistics.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    result = _run_test_session_from_config(
        PROJECT_ROOT / "configs/experiment/v050-test.yaml",
        config,
        "run-a",
        _authorization(),
        bundle_loader=bundle_loader,  # type: ignore[arg-type]
        cell_runner=cell_runner,  # type: ignore[arg-type]
        statistics_writer=statistics_writer,  # type: ignore[arg-type]
    )

    assert len(result.cells) == 28
    assert result.summary_path.is_file()
    ledger = (config.outputs.root / "access-ledger/run-a.jsonl").read_text(encoding="utf-8")
    assert '"event":"test_access_started"' in ledger
    assert '"event":"session_completed"' in ledger


def test_first_test_read_failure_consumes_session_and_seals_incident(tmp_path: Path) -> None:
    loaded = load_experiment_config(PROJECT_ROOT / "configs/experiment/v050-test.yaml")
    assert isinstance(loaded, FrozenTestExperimentConfig)
    config = loaded.model_copy(
        update={"outputs": loaded.outputs.model_copy(update={"root": tmp_path / "formal"})}
    )

    def failing_bundle_loader(
        _config: FrozenTestExperimentConfig,
        _split_name: str,
        _authorization_value: object,
    ) -> FrozenTestBundle:
        raise RuntimeError("synthetic first Test read failure")

    with pytest.raises(RuntimeError, match="synthetic first Test read failure"):
        _run_test_session_from_config(
            PROJECT_ROOT / "configs/experiment/v050-test.yaml",
            config,
            "run-a",
            _authorization(),
            bundle_loader=failing_bundle_loader,  # type: ignore[arg-type]
            cell_runner=lambda *_args: pytest.fail("cell execution must not start"),
            statistics_writer=lambda *_args: pytest.fail("statistics must not start"),
        )

    ledger = config.outputs.root / "access-ledger/run-a.jsonl"
    incident = config.outputs.root / "incidents/run-a.incident.json"
    assert '"test_session_status":"consumed"' in ledger.read_text(encoding="utf-8")
    assert incident.is_file()
