# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_split_audit.evaluation.test_matrix as test_matrix_module
from protein_split_audit.config import load_experiment_config
from protein_split_audit.evaluation.test_matrix import frozen_test_cells, run_frozen_test_protocol
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from tests.test_test_partition_isolation import _authorization

PROJECT_ROOT = Path(__file__).parents[1]
CONFIG = PROJECT_ROOT / "configs/experiment/v050-test.yaml"


def test_frozen_test_matrix_has_exact_stable_membership() -> None:
    config = load_experiment_config(CONFIG)
    assert isinstance(config, FrozenTestExperimentConfig)

    cells = frozen_test_cells(config)

    assert len(cells) == 28
    assert cells[0].cell_id == "v050-test__majority__random"
    assert cells[-1].cell_id == "v050-test__esm2-150m__cluster30"
    assert tuple(cell.method_name for cell in cells[:4]) == ("majority",) * 4
    assert tuple(cell.split_name for cell in cells[:4]) == (
        "random",
        "cluster70",
        "cluster50",
        "cluster30",
    )
    assert len({cell.cell_id for cell in cells}) == 28


def test_frozen_test_matrix_rejects_reordered_or_duplicate_membership() -> None:
    config = load_experiment_config(CONFIG)
    assert isinstance(config, FrozenTestExperimentConfig)
    changed = config.model_copy(update={"methods": tuple(reversed(config.methods))})

    with pytest.raises(ValueError, match="method order"):
        frozen_test_cells(changed)


def test_formal_protocol_writes_review_aggregate_only_after_exact_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    first = SimpleNamespace(root=tmp_path / "run-a", cells=())
    second = SimpleNamespace(root=tmp_path / "run-b", cells=())
    capability = object()
    replay = SimpleNamespace(release_eligible=True, capability=capability)
    calls: list[tuple[object, Path, Path, Path]] = []

    monkeypatch.setattr(test_matrix_module, "find_project_root", lambda _path: PROJECT_ROOT)
    monkeypatch.setattr(
        test_matrix_module,
        "verify_test_authorization",
        lambda _config, _root: authorization,
    )
    monkeypatch.setattr(
        test_matrix_module,
        "run_test_session",
        lambda _config, session, _authorization: first if session == "run-a" else second,
    )
    monkeypatch.setattr(
        test_matrix_module,
        "compare_test_replays",
        lambda _first, _second, _report: replay,
    )

    def write_aggregate(
        replay_capability: object,
        output_dir: Path,
        *,
        config_path: Path,
        attestation_path: Path,
    ) -> SimpleNamespace:
        calls.append((replay_capability, output_dir, config_path, attestation_path))
        return SimpleNamespace(output_dir=output_dir, files=())

    monkeypatch.setattr(
        test_matrix_module,
        "write_test_aggregates",
        write_aggregate,
        raising=False,
    )

    result = run_frozen_test_protocol(CONFIG)

    assert result.aggregate.output_dir.name == "aggregate-review"
    assert calls == [
        (
            capability,
            PROJECT_ROOT / "results/runs/v0.5.0-test/aggregate-review",
            CONFIG,
            authorization.attestation_path,
        )
    ]
