# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from protein_split_audit.evaluation.test_aggregate import write_test_aggregates
from protein_split_audit.experiments.replay import compare_test_replays
from protein_split_audit.provenance import sha256_file
from protein_split_audit.publication import SANITIZED_TEST_FILENAMES
from tests.test_test_replay import _formal_pair
from tests.v050_aggregate_helpers import enrich_formal_pair

PROJECT_ROOT = Path(__file__).parents[1]


def test_aggregate_has_exact_public_file_set_and_rehashes_replay_roots(
    tmp_path: Path,
) -> None:
    attestation = tmp_path / "attestation.yaml"
    attestation.write_text("schema_version: 1\n", encoding="utf-8")
    first, second = _formal_pair(
        tmp_path,
        attestation_sha256=sha256_file(attestation),
    )
    enrich_formal_pair(first, second)
    replay = compare_test_replays(first, second, tmp_path / "replay.json")
    assert replay.capability is not None
    output = tmp_path / "aggregate"
    result = write_test_aggregates(
        replay.capability,
        output,
        config_path=PROJECT_ROOT / "configs/experiment/v050-test.yaml",
        attestation_path=attestation,
    )

    assert {path.name for path in result.files} == SANITIZED_TEST_FILENAMES
    assert {path.name for path in output.iterdir()} == SANITIZED_TEST_FILENAMES

    (first / "statistics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after verification"):
        write_test_aggregates(
            replay.capability,
            tmp_path / "second-aggregate",
            config_path=PROJECT_ROOT / "configs/experiment/v050-test.yaml",
            attestation_path=attestation,
        )
