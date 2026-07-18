# SPDX-License-Identifier: Apache-2.0

"""Hash-bound, Validation-only input loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.features.schemas import ALPHABET
from protein_split_audit.provenance import sha256_bytes, sha256_file


@dataclass(frozen=True, slots=True)
class SequenceRecord:
    """One selected Train or Validation sequence."""

    accession: str
    sequence_sha256: bytes
    label: str
    split: str
    sequence: str


@dataclass(frozen=True, slots=True)
class ValidatedInputBundle:
    """Verified frozen inputs with Test records excluded."""

    records: tuple[SequenceRecord, ...]
    label_order: tuple[str, ...]
    cohort_manifest_sha256: str
    cohort_content_manifest_sha256: str
    cohort_fasta_sha256: str
    split_manifest_sha256: str
    split_content_manifest_sha256: str


def load_json_mapping(path: Path) -> dict[str, object]:
    """Load one JSON object without applying experiment-specific policy."""

    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON manifest: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON manifest must be a mapping: {path.name}")
    return value


def nested_manifest_value(mapping: dict[str, object], *keys: str) -> object:
    """Return one required nested manifest value."""

    value: object = mapping
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"manifest missing field: {'.'.join(keys)}")
        value = value[key]
    return value


def verify_file_hash(path: Path, expected: object, label: str) -> str:
    """Verify one complete file before any structured projection is opened."""

    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"invalid expected {label} hash")
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"{label} hash mismatch")
    return observed


def load_selected_fasta(path: Path, selected: frozenset[str]) -> dict[str, str]:
    """Parse only selected FASTA records; skipped sequence lines are never joined."""

    sequences: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] | None = None

    def finish() -> None:
        nonlocal current, chunks
        if current is None or chunks is None:
            return
        if current in sequences:
            raise ValueError(f"duplicate selected FASTA accession: {current}")
        sequences[current] = "".join(chunks)

    with path.open("r", encoding="utf-8", newline=None) as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                finish()
                token = line[1:].split(maxsplit=1)[0]
                parts = token.split("|")
                accession = parts[1] if len(parts) == 3 and parts[0] == "sp" else token
                current = accession if accession in selected else None
                chunks = [] if current is not None else None
            elif chunks is not None:
                chunks.append(line)
    finish()
    return sequences


def _load_inputs(
    *,
    cohort_manifest: Path,
    cohort_content_manifest: Path,
    cohort_fasta: Path,
    split_manifest: Path,
    split_content_manifest: Path,
    include_labels: bool,
) -> ValidatedInputBundle:
    """Verify frozen identities and materialize Train/Validation records only."""

    cohort_content = load_json_mapping(cohort_content_manifest)
    split_content = load_json_mapping(split_content_manifest)
    cohort_hash = verify_file_hash(
        cohort_manifest,
        nested_manifest_value(cohort_content, "artifacts", "cohort_manifest", "file_sha256"),
        "cohort manifest",
    )
    fasta_hash = verify_file_hash(
        cohort_fasta,
        nested_manifest_value(cohort_content, "artifacts", "fasta", "file_sha256"),
        "FASTA",
    )
    split_hash = verify_file_hash(
        split_manifest,
        nested_manifest_value(split_content, "artifact", "file_sha256"),
        "split manifest",
    )
    cohort_content_hash = sha256_file(cohort_content_manifest)
    if split_content.get("cohort_content_manifest_sha256") != cohort_content_hash:
        raise ValueError("split parent cohort content hash mismatch")

    try:
        assignments = pq.read_table(
            split_manifest,
            columns=["accession", "sequence_sha256", "split"],
            filters=[("split", "in", ["train", "validation"])],
        ).to_pylist()
    except (OSError, KeyError) as error:
        raise ValueError("unable to read split assignment projection") from error
    selected_rows = assignments
    selected_accessions = [str(row["accession"]) for row in selected_rows]
    if len(selected_accessions) != len(set(selected_accessions)):
        raise ValueError("selected split contains duplicate accessions")
    selected = frozenset(selected_accessions)
    if not selected:
        raise ValueError("split has no Train or Validation records")

    try:
        cohort_columns = ["accession", "sequence_sha256", "sequence_length"]
        if include_labels:
            cohort_columns.append("ec_level_2")
        cohort_rows = pq.read_table(
            cohort_manifest,
            columns=cohort_columns,
            filters=[("accession", "in", sorted(selected))],
        ).to_pylist()
    except (OSError, KeyError) as error:
        raise ValueError("unable to read selected cohort rows") from error
    by_accession = {str(row["accession"]): row for row in cohort_rows}
    if set(by_accession) != selected:
        raise ValueError("selected split and cohort accessions differ")

    fasta_sequences = load_selected_fasta(cohort_fasta, selected)
    if set(fasta_sequences) != selected:
        raise ValueError("selected cohort and FASTA accessions differ")
    assignment_by_accession = {str(row["accession"]): row for row in selected_rows}
    records: list[SequenceRecord] = []
    allowed = frozenset(ALPHABET)
    for accession in sorted(selected):
        cohort_row = by_accession[accession]
        assignment = assignment_by_accession[accession]
        sequence = fasta_sequences[accession]
        if not sequence or not set(sequence).issubset(allowed):
            raise ValueError(f"selected sequence is invalid: {accession}")
        digest = sha256_bytes(sequence.encode("ascii"))
        digest_bytes = bytes.fromhex(digest)
        if digest_bytes != cohort_row["sequence_sha256"]:
            raise ValueError(f"selected sequence hash mismatch: {accession}")
        if digest_bytes != assignment["sequence_sha256"]:
            raise ValueError(f"split sequence hash mismatch: {accession}")
        if len(sequence) != cohort_row["sequence_length"]:
            raise ValueError(f"selected sequence length mismatch: {accession}")
        records.append(
            SequenceRecord(
                accession=accession,
                sequence_sha256=digest_bytes,
                label=str(cohort_row["ec_level_2"]) if include_labels else "",
                split=str(assignment["split"]),
                sequence=sequence,
            )
        )

    labels: object = cohort_content.get("selected_labels")
    if (
        not isinstance(labels, list)
        or not labels
        or not all(isinstance(item, str) for item in labels)
    ):
        raise ValueError("cohort content manifest has invalid selected_labels")
    label_order = tuple(labels)
    return ValidatedInputBundle(
        records=tuple(records),
        label_order=label_order,
        cohort_manifest_sha256=cohort_hash,
        cohort_content_manifest_sha256=cohort_content_hash,
        cohort_fasta_sha256=fasta_hash,
        split_manifest_sha256=split_hash,
        split_content_manifest_sha256=sha256_file(split_content_manifest),
    )


def load_feature_inputs(
    *,
    cohort_manifest: Path,
    cohort_content_manifest: Path,
    cohort_fasta: Path,
    split_manifest: Path,
    split_content_manifest: Path,
) -> ValidatedInputBundle:
    """Load Train/Validation sequences without projecting row-level target labels."""

    return _load_inputs(
        cohort_manifest=cohort_manifest,
        cohort_content_manifest=cohort_content_manifest,
        cohort_fasta=cohort_fasta,
        split_manifest=split_manifest,
        split_content_manifest=split_content_manifest,
        include_labels=False,
    )


def load_validation_inputs(
    *,
    cohort_manifest: Path,
    cohort_content_manifest: Path,
    cohort_fasta: Path,
    split_manifest: Path,
    split_content_manifest: Path,
) -> ValidatedInputBundle:
    """Load verified Train/Validation sequences and labels for evaluation."""

    return _load_inputs(
        cohort_manifest=cohort_manifest,
        cohort_content_manifest=cohort_content_manifest,
        cohort_fasta=cohort_fasta,
        split_manifest=split_manifest,
        split_content_manifest=split_content_manifest,
        include_labels=True,
    )


__all__ = [
    "SequenceRecord",
    "ValidatedInputBundle",
    "load_feature_inputs",
    "load_json_mapping",
    "load_selected_fasta",
    "load_validation_inputs",
    "nested_manifest_value",
    "verify_file_hash",
]
