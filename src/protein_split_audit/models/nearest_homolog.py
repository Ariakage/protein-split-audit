# SPDX-License-Identifier: Apache-2.0

"""Deterministic Train-only MMseqs2 nearest-homolog baseline."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from protein_split_audit.attestations.test_access import (
    VerifiedTestAuthorization,
    require_verified_authorization,
)
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.majority import fit_majority
from protein_split_audit.models.schemas import NearestHomologModelConfig
from protein_split_audit.similarity.mmseqs import MmseqsRunContext, MmseqsRunResult, run_mmseqs

_FORMAT = "query,target,fident,qcov,tcov,evalue,bits"
_HEADER = _FORMAT.replace(",", "\t")


@dataclass(frozen=True, slots=True)
class HomologHit:
    """One accepted Validation-to-Train hit."""

    query_accession: str
    target_accession: str
    percent_identity: float
    query_coverage: float
    target_coverage: float
    evalue: float
    bitscore: float


@dataclass(frozen=True, slots=True)
class NearestPrediction:
    """One nearest-homolog prediction or explicit no-hit fallback."""

    query_accession: str
    true_label: str
    nearest_train_accession: str | None
    nearest_train_label: str | None
    predicted_label: str
    percent_identity: float | None
    query_coverage: float | None
    target_coverage: float | None
    bitscore: float | None
    evalue: float | None
    no_hit: bool


@dataclass(frozen=True, slots=True)
class NearestResult:
    """Detailed rows and separate no-hit aggregates."""

    rows: tuple[NearestPrediction, ...]
    no_hit_count: int
    no_hit_rate: float
    no_hit_correct_count: int


def _hit_key(hit: HomologHit) -> tuple[float, float, float, float, float, str]:
    return (
        -hit.bitscore,
        hit.evalue,
        -hit.percent_identity,
        -hit.query_coverage,
        -hit.target_coverage,
        hit.target_accession,
    )


def _predict_nearest_for_partition(
    records: Sequence[SequenceRecord],
    hits: Sequence[HomologHit],
    *,
    query_partition: str,
) -> NearestResult:
    """Select stable top hits for one already-authorized query partition."""

    train = {record.accession: record for record in records if record.split == "train"}
    queries = {record.accession: record for record in records if record.split == query_partition}
    majority = fit_majority([record.label for record in train.values()])
    grouped: dict[str, list[HomologHit]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    display_partition = "Validation" if query_partition == "validation" else "Test"
    for hit in hits:
        if hit.query_accession not in queries:
            raise ValueError(f"nearest-homolog query must belong to {display_partition}")
        if hit.target_accession not in train:
            raise ValueError("nearest-homolog target must belong to Train")
        if not (
            0.0 <= hit.percent_identity <= 1.0
            and 0.8 <= hit.query_coverage <= 1.0
            and 0.8 <= hit.target_coverage <= 1.0
            and 0.0 <= hit.evalue <= 0.001
            and hit.bitscore >= 0.0
        ):
            raise ValueError("nearest-homolog hit violates the frozen predicate")
        key = (hit.query_accession, hit.target_accession)
        if key in seen:
            raise ValueError("nearest-homolog output contains a duplicate directed hit")
        seen.add(key)
        grouped[hit.query_accession].append(hit)

    rows: list[NearestPrediction] = []
    for accession in sorted(queries):
        query = queries[accession]
        candidates = grouped.get(accession, [])
        if not candidates:
            rows.append(
                NearestPrediction(
                    accession,
                    query.label,
                    None,
                    None,
                    majority.label,
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                )
            )
            continue
        best = min(candidates, key=_hit_key)
        target = train[best.target_accession]
        rows.append(
            NearestPrediction(
                accession,
                query.label,
                target.accession,
                target.label,
                target.label,
                best.percent_identity,
                best.query_coverage,
                best.target_coverage,
                best.bitscore,
                best.evalue,
                False,
            )
        )
    no_hit_rows = [row for row in rows if row.no_hit]
    return NearestResult(
        rows=tuple(rows),
        no_hit_count=len(no_hit_rows),
        no_hit_rate=len(no_hit_rows) / len(rows) if rows else 0.0,
        no_hit_correct_count=sum(row.predicted_label == row.true_label for row in no_hit_rows),
    )


def predict_nearest(
    records: Sequence[SequenceRecord],
    hits: Sequence[HomologHit],
) -> NearestResult:
    """Select stable Validation hits and apply an explicit Train-majority fallback."""

    return _predict_nearest_for_partition(records, hits, query_partition="validation")


def predict_test_nearest(
    records: Sequence[SequenceRecord],
    hits: Sequence[HomologHit],
    authorization: VerifiedTestAuthorization,
) -> NearestResult:
    """Predict unlabeled Test queries after capability verification."""

    require_verified_authorization(authorization)
    return _predict_nearest_for_partition(records, hits, query_partition="test")


def parse_hits(path: Path) -> tuple[HomologHit, ...]:
    """Parse normalized MMseqs2 output without relying on its row order."""

    text = path.read_text(encoding="utf-8")
    if text == "":
        return ()
    if "\r" in text or not text.endswith("\n"):
        raise ValueError("nearest-homolog TSV must use LF and end with LF")
    lines = text[:-1].split("\n")
    if lines[0] != _HEADER:
        raise ValueError("nearest-homolog TSV header is invalid")
    rows: list[HomologHit] = []
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError(f"nearest-homolog TSV line {line_number} must have seven fields")
        try:
            rows.append(
                HomologHit(
                    fields[0],
                    fields[1],
                    float(fields[2]),
                    float(fields[3]),
                    float(fields[4]),
                    float(fields[5]),
                    float(fields[6]),
                )
            )
        except ValueError as error:
            raise ValueError(
                f"nearest-homolog TSV line {line_number} has an invalid number"
            ) from error
    return tuple(rows)


def _write_subset_fasta(records: Sequence[SequenceRecord], split: str, path: Path) -> Path:
    selected = sorted(
        (record for record in records if record.split == split),
        key=lambda row: row.accession,
    )
    if not selected:
        raise ValueError(f"nearest-homolog {split} FASTA would be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f">{record.accession}\n{record.sequence}\n" for record in selected),
        encoding="utf-8",
        newline="\n",
    )
    return path


def write_subset_fasta(records: Sequence[SequenceRecord], split: str, path: Path) -> Path:
    """Write a deterministic Train or Validation FASTA and reject Test."""

    if split not in {"train", "validation"}:
        raise ValueError("nearest-homolog FASTA split must be Train or Validation")
    return _write_subset_fasta(records, split, path)


def write_test_subset_fasta(
    records: Sequence[SequenceRecord],
    split: str,
    path: Path,
    authorization: VerifiedTestAuthorization,
) -> Path:
    """Write deterministic Train/Test FASTA only with verified Test authority."""

    require_verified_authorization(authorization)
    if split not in {"train", "test"}:
        raise ValueError("formal nearest-homolog FASTA split must be Train or Test")
    return _write_subset_fasta(records, split, path)


def build_nearest_argv(
    config: NearestHomologModelConfig,
    *,
    query_fasta: Path,
    target_fasta: Path,
    output_tsv: Path,
    temp_dir: Path,
    train_count: int,
) -> tuple[str, ...]:
    """Build the frozen Validation-to-Train MMseqs2 command."""

    if train_count <= 0:
        raise ValueError("train_count must be positive")
    paths = (query_fasta, target_fasta, output_tsv, temp_dir)
    if any(not path.is_absolute() for path in paths):
        raise ValueError("nearest-homolog command paths must be absolute")
    search = config.search
    return (
        config.runtime.executable,
        "easy-search",
        str(query_fasta),
        str(target_fasta),
        str(output_tsv),
        str(temp_dir),
        "--search-type",
        str(search.search_type),
        "--min-seq-id",
        f"{search.minimum_identity:.1f}",
        "-c",
        f"{search.minimum_coverage:.2f}",
        "--cov-mode",
        str(search.coverage_mode),
        "--alignment-mode",
        str(search.alignment_mode),
        "--seq-id-mode",
        str(search.sequence_identity_mode),
        "--max-seqs",
        str(train_count),
        "-s",
        f"{search.sensitivity:g}",
        "-e",
        f"{search.evalue_threshold:g}",
        "--format-mode",
        "4",
        "--format-output",
        _FORMAT,
        "--threads",
        str(config.runtime.threads),
    )


def execute_nearest(
    records: Sequence[SequenceRecord],
    config: NearestHomologModelConfig,
) -> tuple[NearestResult, MmseqsRunResult]:
    """Run the controlled formal MMseqs2 search and parse stable predictions."""

    train_count = sum(record.split == "train" for record in records)
    context = MmseqsRunContext.create(
        cache_root=config.runtime.cache_root,
        timeout_seconds=config.runtime.timeout_seconds,
        expected_output_names=("hits.tsv",),
    )
    query = write_subset_fasta(records, "validation", context.staging_dir / "validation.fasta")
    target = write_subset_fasta(records, "train", context.staging_dir / "train.fasta")
    argv = build_nearest_argv(
        config,
        query_fasta=query,
        target_fasta=target,
        output_tsv=context.expected_outputs[0],
        temp_dir=context.staging_dir / "tmp",
        train_count=train_count,
    )
    run = run_mmseqs(argv, context)
    return predict_nearest(records, parse_hits(run.outputs[0])), run


def execute_test_nearest(
    records: Sequence[SequenceRecord],
    config: NearestHomologModelConfig,
    authorization: VerifiedTestAuthorization,
) -> tuple[NearestResult, MmseqsRunResult]:
    """Run one capability-gated Test-to-Train MMseqs2 search."""

    require_verified_authorization(authorization)
    train_count = sum(record.split == "train" for record in records)
    context = MmseqsRunContext.create(
        cache_root=config.runtime.cache_root,
        timeout_seconds=config.runtime.timeout_seconds,
        expected_output_names=("hits.tsv",),
    )
    query = write_test_subset_fasta(
        records,
        "test",
        context.staging_dir / "test.fasta",
        authorization,
    )
    target = write_test_subset_fasta(
        records,
        "train",
        context.staging_dir / "train.fasta",
        authorization,
    )
    argv = build_nearest_argv(
        config,
        query_fasta=query,
        target_fasta=target,
        output_tsv=context.expected_outputs[0],
        temp_dir=context.staging_dir / "tmp",
        train_count=train_count,
    )
    run = run_mmseqs(argv, context)
    return predict_test_nearest(records, parse_hits(run.outputs[0]), authorization), run


__all__ = [
    "HomologHit",
    "NearestPrediction",
    "NearestResult",
    "build_nearest_argv",
    "execute_nearest",
    "execute_test_nearest",
    "parse_hits",
    "predict_nearest",
    "predict_test_nearest",
    "write_subset_fasta",
    "write_test_subset_fasta",
]
