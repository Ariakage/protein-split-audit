# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from protein_split_audit.config import load_feature_config
from tests.test_length_features import _load_bundle
from tests.v030_helpers import write_tiny_inputs

PROJECT_ROOT = Path(__file__).parents[1]


def test_feature_loading_does_not_project_target_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import protein_split_audit.features.validation as validation

    inputs = write_tiny_inputs(tmp_path)
    original = validation.pq.read_table
    projected: list[tuple[str, ...]] = []

    def recording_read_table(*args: object, **kwargs: object) -> object:
        columns = kwargs.get("columns")
        if isinstance(columns, list):
            projected.append(tuple(str(value) for value in columns))
        return original(*args, **kwargs)

    monkeypatch.setattr(validation.pq, "read_table", recording_read_table)
    validation.load_feature_inputs(
        cohort_manifest=inputs.cohort,
        cohort_content_manifest=inputs.cohort_content,
        cohort_fasta=inputs.fasta,
        split_manifest=inputs.split,
        split_content_manifest=inputs.split_content,
    )

    assert projected
    assert all("ec_level_2" not in columns for columns in projected)


def test_feature_loading_accepts_frozen_cohort_fasta_headers(tmp_path: Path) -> None:
    from protein_split_audit.features.validation import load_feature_inputs

    inputs = write_tiny_inputs(tmp_path, official_headers=True)
    bundle = load_feature_inputs(
        cohort_manifest=inputs.cohort,
        cohort_content_manifest=inputs.cohort_content,
        cohort_fasta=inputs.fasta,
        split_manifest=inputs.split,
        split_content_manifest=inputs.split_content,
    )

    assert tuple(record.accession for record in bundle.records) == ("A0", "A1")


def test_dense_feature_cache_round_trip_is_identity_bound(tmp_path: Path) -> None:
    from protein_split_audit.features.cache import load_feature_cache, write_feature_cache
    from protein_split_audit.features.length import extract_length

    bundle = _load_bundle(write_tiny_inputs(tmp_path / "inputs"))
    config = load_feature_config(PROJECT_ROOT / "configs/feature/length.yaml")
    matrix = extract_length(bundle.records)

    written = write_feature_cache(tmp_path / "cache", config, bundle, matrix)
    loaded = load_feature_cache(written.directory, config, bundle)

    assert written.cache_key == loaded.cache_key
    assert loaded.accessions == ("A0", "A1")
    np.testing.assert_array_equal(loaded.matrix, matrix)
