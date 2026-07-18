# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from protein_split_audit.evaluation.test_inputs import load_frozen_test_bundle
from tests.test_test_partition_isolation import _authorization, _write_inputs


def test_changed_cohort_bytes_fail_before_any_parquet_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_inputs(tmp_path)
    config.cohort.manifest.write_bytes(config.cohort.manifest.read_bytes() + b"tamper")

    import protein_split_audit.evaluation.test_inputs as module

    monkeypatch.setattr(
        module.pq,
        "read_table",
        lambda *_args, **_kwargs: pytest.fail("Parquet opened before complete byte hashes passed"),
    )
    with pytest.raises(ValueError, match="cohort manifest hash mismatch"):
        load_frozen_test_bundle(config, "random", _authorization())


def test_bundle_records_all_complete_input_and_component_hashes(tmp_path: Path) -> None:
    config = _write_inputs(tmp_path)

    bundle = load_frozen_test_bundle(config, "cluster30", _authorization())

    assert set(bundle.input_hashes) == {
        "cohort_manifest_sha256",
        "cohort_content_manifest_sha256",
        "cohort_fasta_sha256",
        "split_manifest_sha256",
        "split_content_manifest_sha256",
        "test_component_inventory_sha256",
    }
    assert all(len(value) == 64 for value in bundle.input_hashes.values())
