# SPDX-License-Identifier: Apache-2.0

"""Standalone validation boundary for local embedding caches."""

from __future__ import annotations

from pathlib import Path

from protein_split_audit.embeddings.cache import SplitName, load_embedding_cache
from protein_split_audit.embeddings.schemas import (
    EmbeddingConfig,
    EmbeddingManifest,
    ModelSnapshotManifest,
)
from protein_split_audit.features.validation import ValidatedInputBundle


def validate_embedding_cache(
    directory: Path,
    config: EmbeddingConfig,
    snapshot: ModelSnapshotManifest,
    bundle: ValidatedInputBundle,
    *,
    split_name: SplitName,
    dependency_versions: dict[str, str],
) -> EmbeddingManifest:
    """Recompute a cache identity and return its verified manifest."""

    return load_embedding_cache(
        directory,
        config,
        snapshot,
        bundle,
        split_name=split_name,
        dependency_versions=dependency_versions,
    ).manifest


__all__ = ["validate_embedding_cache"]
