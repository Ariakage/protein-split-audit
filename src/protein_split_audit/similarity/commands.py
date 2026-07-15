# SPDX-License-Identifier: Apache-2.0

"""Pure, deterministic MMseqs2 argument builders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from protein_split_audit.similarity.schemas import (
    AuditSearchParameters,
    ClusterParameters,
    MmseqsRuntimeConfig,
    SelfSearchParameters,
)

_SEARCH_FORMAT = "query,target,fident,qcov,tcov,evalue,bits"


def _require_positive_count(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_absolute_paths(paths: tuple[Path, ...]) -> None:
    if any(not path.is_absolute() for path in paths):
        raise ValueError("MMseqs2 command paths must be absolute")


@dataclass(frozen=True, slots=True)
class ClusterCommandPaths:
    """Execution-only paths for one descriptive clustering command."""

    input_fasta: Path
    output_prefix: Path
    temp_dir: Path

    def __post_init__(self) -> None:
        _require_absolute_paths((self.input_fasta, self.output_prefix, self.temp_dir))


@dataclass(frozen=True, slots=True)
class SearchCommandPaths:
    """Execution-only paths for one fixed-parameter search command."""

    query_fasta: Path
    target_fasta: Path
    output_tsv: Path
    temp_dir: Path

    def __post_init__(self) -> None:
        _require_absolute_paths(
            (self.query_fasta, self.target_fasta, self.output_tsv, self.temp_dir)
        )


def build_cluster_argv(
    config: ClusterParameters,
    runtime: MmseqsRuntimeConfig,
    sequence_count: int,
    *,
    paths: ClusterCommandPaths,
) -> Sequence[str]:
    """Build the fixed-order ``easy-cluster`` argument tuple."""

    _require_positive_count(sequence_count, "sequence_count")
    return (
        runtime.executable,
        "easy-cluster",
        str(paths.input_fasta),
        str(paths.output_prefix),
        str(paths.temp_dir),
        "--min-seq-id",
        f"{config.min_sequence_identity:.2f}",
        "-c",
        f"{config.minimum_coverage:.2f}",
        "--cov-mode",
        str(config.coverage_mode),
        "--alignment-mode",
        str(config.alignment_mode),
        "--seq-id-mode",
        str(config.sequence_identity_mode),
        "--cluster-mode",
        str(config.cluster_mode),
        "--cluster-reassign",
        "1" if config.cluster_reassign else "0",
        "--max-seqs",
        str(sequence_count),
        "-s",
        f"{config.sensitivity:g}",
        "-e",
        f"{config.evalue:g}",
        "--threads",
        str(runtime.threads),
    )


def build_self_search_argv(
    config: SelfSearchParameters,
    runtime: MmseqsRuntimeConfig,
    sequence_count: int,
    *,
    paths: SearchCommandPaths,
) -> Sequence[str]:
    """Build the fixed-order all-vs-all ``easy-search`` argument tuple."""

    _require_positive_count(sequence_count, "sequence_count")
    return (
        runtime.executable,
        "easy-search",
        str(paths.query_fasta),
        str(paths.target_fasta),
        str(paths.output_tsv),
        str(paths.temp_dir),
        "--search-type",
        str(config.search_type),
        "--min-seq-id",
        f"{config.min_sequence_identity:.2f}",
        "-c",
        f"{config.minimum_coverage:.2f}",
        "--cov-mode",
        str(config.coverage_mode),
        "--alignment-mode",
        str(config.alignment_mode),
        "--seq-id-mode",
        str(config.sequence_identity_mode),
        "--max-seqs",
        str(sequence_count),
        "-s",
        f"{config.sensitivity:g}",
        "-e",
        f"{config.evalue:g}",
        "--format-mode",
        str(config.format_mode),
        "--format-output",
        _SEARCH_FORMAT,
        "--threads",
        str(runtime.threads),
    )


def build_audit_argv(
    config: AuditSearchParameters,
    runtime: MmseqsRuntimeConfig,
    train_count: int,
    *,
    paths: SearchCommandPaths,
) -> Sequence[str]:
    """Build the fixed-order test-to-train ``easy-search`` argument tuple."""

    _require_positive_count(train_count, "train_count")
    return (
        runtime.executable,
        "easy-search",
        str(paths.query_fasta),
        str(paths.target_fasta),
        str(paths.output_tsv),
        str(paths.temp_dir),
        "--search-type",
        str(config.search_type),
        "--min-seq-id",
        f"{config.min_sequence_identity:.1f}",
        "-c",
        f"{config.minimum_coverage:.2f}",
        "--cov-mode",
        str(config.coverage_mode),
        "--alignment-mode",
        str(config.alignment_mode),
        "--seq-id-mode",
        str(config.sequence_identity_mode),
        "--max-seqs",
        str(train_count),
        "-s",
        f"{config.sensitivity:g}",
        "-e",
        f"{config.evalue:g}",
        "--format-mode",
        str(config.format_mode),
        "--format-output",
        _SEARCH_FORMAT,
        "--threads",
        str(runtime.threads),
    )


__all__ = [
    "ClusterCommandPaths",
    "SearchCommandPaths",
    "build_audit_argv",
    "build_cluster_argv",
    "build_self_search_argv",
]
