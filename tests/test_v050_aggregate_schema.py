# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
from pathlib import Path

from protein_split_audit.evaluation.test_aggregate import write_test_aggregates
from protein_split_audit.experiments.replay import compare_test_replays
from protein_split_audit.provenance import sha256_file
from tests.test_test_replay import _formal_pair
from tests.v050_aggregate_helpers import enrich_formal_pair

PROJECT_ROOT = Path(__file__).parents[1]


def _aggregate(tmp_path: Path) -> Path:
    attestation = tmp_path / "attestation.yaml"
    attestation.write_text(
        "# SPDX-License-Identifier: CC-BY-4.0\nschema_version: 1\n",
        encoding="utf-8",
    )
    first, second = _formal_pair(
        tmp_path,
        attestation_sha256=sha256_file(attestation),
    )
    enrich_formal_pair(first, second)
    report = compare_test_replays(first, second, tmp_path / "replay.json")
    assert report.capability is not None
    output = tmp_path / "aggregate"
    write_test_aggregates(
        report.capability,
        output,
        config_path=PROJECT_ROOT / "configs/experiment/v050-test.yaml",
        attestation_path=attestation,
    )
    return output


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_sanitized_aggregate_has_frozen_table_shapes(tmp_path: Path) -> None:
    output = _aggregate(tmp_path)

    assert len(_rows(output / "test_summary.csv")) == 28
    assert len(_rows(output / "test_per_class.csv")) == 140
    assert len(_rows(output / "confusion_matrices.csv")) == 700
    assert len(_rows(output / "generalization_gap.csv")) == 21
    assert len(_rows(output / "method_comparisons.csv")) == 40
    assert len(_rows(output / "nearest_homolog_summary.csv")) == 4
    assert len(_rows(output / "confidence_intervals.csv")) == 117
