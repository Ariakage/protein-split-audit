# SPDX-License-Identifier: Apache-2.0

"""Label-free classical feature extraction entry point."""

from __future__ import annotations

from pathlib import Path

from protein_split_audit.config import load_feature_config
from protein_split_audit.features.amino_acid_composition import extract_aac
from protein_split_audit.features.cache import (
    FeatureCache,
    FeatureMatrix,
    get_or_create_feature_cache,
)
from protein_split_audit.features.kmer import extract_kmer3
from protein_split_audit.features.length import extract_length
from protein_split_audit.features.validation import ValidatedInputBundle, load_feature_inputs


def _extract(kind: str, bundle: ValidatedInputBundle) -> FeatureMatrix:
    if kind == "length":
        return extract_length(bundle.records)
    if kind == "aac":
        return extract_aac(bundle.records)
    if kind == "kmer3":
        return extract_kmer3(bundle.records)
    raise ValueError(f"unsupported feature kind: {kind}")


def extract_feature_cache(
    *,
    config_path: Path,
    cohort_manifest: Path,
    cohort_content_manifest: Path,
    cohort_fasta: Path,
    split_manifest: Path,
    split_content_manifest: Path,
    cache_root: Path,
) -> FeatureCache:
    """Extract or verify an immutable Train/Validation feature cache."""

    config = load_feature_config(config_path)
    bundle = load_feature_inputs(
        cohort_manifest=cohort_manifest,
        cohort_content_manifest=cohort_content_manifest,
        cohort_fasta=cohort_fasta,
        split_manifest=split_manifest,
        split_content_manifest=split_content_manifest,
    )
    matrix = _extract(config.kind, bundle)
    return get_or_create_feature_cache(cache_root, config, bundle, matrix)


__all__ = ["extract_feature_cache"]
