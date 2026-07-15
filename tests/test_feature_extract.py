# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from tests.v030_helpers import write_tiny_inputs

PROJECT_ROOT = Path(__file__).parents[1]


def test_feature_extract_writes_train_validation_cache_only(tmp_path: Path) -> None:
    from protein_split_audit.features.extract import extract_feature_cache

    inputs = write_tiny_inputs(tmp_path / "inputs")
    result = extract_feature_cache(
        config_path=PROJECT_ROOT / "configs/feature/length.yaml",
        cohort_manifest=inputs.cohort,
        cohort_content_manifest=inputs.cohort_content,
        cohort_fasta=inputs.fasta,
        split_manifest=inputs.split,
        split_content_manifest=inputs.split_content,
        cache_root=tmp_path / "cache",
    )

    assert result.accessions == ("A0", "A1")
    assert result.matrix.shape == (2, 1)
    assert (result.directory / "manifest.json").is_file()
