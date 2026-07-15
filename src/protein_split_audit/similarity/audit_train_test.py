# SPDX-License-Identifier: Apache-2.0

"""Independent test-to-train similarity audit parsing and policy gates."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit import __version__
from protein_split_audit.cohort.artifacts import CohortContentManifest
from protein_split_audit.config import SimilarityConfigDocument
from protein_split_audit.data.build_candidates import PARQUET_WRITER_SETTINGS
from protein_split_audit.provenance import (
    git_metadata,
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.publication import PublicationError, publish_bundle
from protein_split_audit.similarity.commands import SearchCommandPaths, build_audit_argv
from protein_split_audit.similarity.mmseqs import MmseqsRunContext, run_mmseqs
from protein_split_audit.similarity.parse_clusters import CandidateIndex, PairTsvError, SequenceNode
from protein_split_audit.similarity.schemas import AuditConfig

_HEADER = "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits"
_ZERO = Decimal(0)
_ONE = Decimal(1)

AUDIT_MANIFEST_SCHEMA = pa.schema(
    [
        pa.field("test_accession", pa.string(), nullable=False),
        pa.field("test_ec_level_2", pa.string(), nullable=False),
        pa.field("nearest_train_accession", pa.string(), nullable=True),
        pa.field("nearest_train_ec_level_2", pa.string(), nullable=True),
        pa.field("fident", pa.decimal128(7, 6), nullable=True),
        pa.field("qcov", pa.decimal128(7, 6), nullable=True),
        pa.field("tcov", pa.decimal128(7, 6), nullable=True),
        pa.field("evalue", pa.float64(), nullable=True),
        pa.field("bits", pa.float64(), nullable=True),
        pa.field("same_label", pa.bool_(), nullable=True),
        pa.field("threshold_violation", pa.bool_(), nullable=False),
        pa.field("no_match", pa.bool_(), nullable=False),
    ]
)


class SimilarityAuditError(RuntimeError):
    """Raised when audit output is malformed or violates a grouped-split gate."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One validated observed test-to-train hit."""

    test_accession: str
    train_accession: str
    fident: Decimal
    qcov: Decimal
    tcov: Decimal
    evalue: Decimal
    bits: Decimal


@dataclass(frozen=True, slots=True)
class NearestTrain:
    """Best observed train neighbor or an explicit no-match row."""

    test_accession: str
    train_accession: str | None
    fident: Decimal | None
    qcov: Decimal | None
    tcov: Decimal | None
    evalue: Decimal | None
    bits: Decimal | None
    no_match: bool


@dataclass(frozen=True, slots=True)
class AuditedNearestTrain:
    """Nearest row enriched with labels and the strategy threshold status."""

    nearest: NearestTrain
    test_label: str
    train_label: str | None
    same_label: bool | None
    threshold_violation: bool


@dataclass(frozen=True, slots=True)
class SimilarityAudit:
    """Deterministic record rows plus aggregate leakage evidence."""

    rows: tuple[AuditedNearestTrain, ...]
    violation_count: int
    no_match_count: int
    same_label_count: int
    exceedance_counts: dict[str, int]
    release_eligible: bool


@dataclass(frozen=True, slots=True)
class SerializedAudit:
    """Deterministic audit row artifact bytes and hashes."""

    parquet_bytes: bytes
    file_sha256: str
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class SimilarityAuditArtifacts:
    """Published audit artifact locations and release state."""

    audit_manifest_path: Path
    content_manifest_path: Path
    summary_path: Path
    train_fasta_path: Path
    test_fasta_path: Path
    content_manifest_sha256: str
    release_eligible: bool


def _resolve(index: CandidateIndex, value: str, role: str) -> str:
    try:
        return index.resolve(value).accession
    except PairTsvError as error:
        raise SimilarityAuditError(
            f"audit table contains unknown {role} identifier {value!r}"
        ) from error


def parse_search_tsv(
    path: Path,
    test: CandidateIndex,
    train: CandidateIndex,
) -> tuple[SearchHit, ...]:
    """Parse fixed-format audit hits; a completely empty file means no observed matches."""

    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise SimilarityAuditError(f"audit search table not found: {path}") from error
    except OSError as error:
        raise SimilarityAuditError(f"audit search table could not be read: {path}") from error
    if content == b"":
        return ()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SimilarityAuditError("audit search table must be valid UTF-8") from error
    if "\r" in text or not text.endswith("\n"):
        raise SimilarityAuditError("audit search table must use LF and end with LF")
    lines = text[:-1].split("\n")
    if lines[0] != _HEADER:
        raise SimilarityAuditError("audit search table header is invalid")
    hits: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != 7:
            raise SimilarityAuditError(
                f"audit search line {line_number} must contain exactly seven fields"
            )
        query, target, *numbers = fields
        try:
            fident, qcov, tcov, evalue, bits = (Decimal(value) for value in numbers)
        except InvalidOperation as error:
            raise SimilarityAuditError(
                f"audit search line {line_number} contains an invalid number"
            ) from error
        if not all(value.is_finite() for value in (fident, qcov, tcov, evalue, bits)):
            raise SimilarityAuditError("audit search metrics must be finite")
        if (
            not _ZERO <= fident <= _ONE
            or not Decimal("0.80") <= qcov <= _ONE
            or not Decimal("0.80") <= tcov <= _ONE
            or not _ZERO <= evalue <= Decimal("0.001")
            or bits < _ZERO
        ):
            raise SimilarityAuditError("audit search metrics violate the fixed predicate")
        test_accession = _resolve(test, query, "test")
        train_accession = _resolve(train, target, "train")
        key = (test_accession, train_accession)
        if key in seen:
            raise SimilarityAuditError("audit search contains a duplicate directed hit")
        seen.add(key)
        hits.append(
            SearchHit(
                test_accession,
                train_accession,
                fident,
                qcov,
                tcov,
                evalue,
                bits,
            )
        )
    return tuple(sorted(hits, key=lambda hit: (hit.test_accession, hit.train_accession)))


def _hit_key(hit: SearchHit) -> tuple[Decimal, Decimal, Decimal, Decimal, str, str]:
    return (
        -hit.fident,
        -min(hit.qcov, hit.tcov),
        -hit.bits,
        hit.evalue,
        hit.train_accession,
        hit.test_accession,
    )


def select_nearest_train(
    test: CandidateIndex,
    hits: Sequence[SearchHit],
) -> tuple[NearestTrain, ...]:
    """Represent every test sequence using the deterministic best observed hit."""

    by_test: dict[str, list[SearchHit]] = defaultdict(list)
    expected = {node.accession for node in test.nodes}
    for hit in hits:
        if hit.test_accession not in expected:
            raise SimilarityAuditError("audit hit refers to an unknown test sequence")
        by_test[hit.test_accession].append(hit)
    rows: list[NearestTrain] = []
    for node in test.nodes:
        candidates = by_test.get(node.accession, [])
        if not candidates:
            rows.append(NearestTrain(node.accession, None, None, None, None, None, None, True))
            continue
        best = min(candidates, key=_hit_key)
        rows.append(
            NearestTrain(
                best.test_accession,
                best.train_accession,
                best.fident,
                best.qcov,
                best.tcov,
                best.evalue,
                best.bits,
                False,
            )
        )
    return tuple(rows)


def audit_observed_hits(
    nearest: Sequence[NearestTrain],
    hits: Sequence[SearchHit],
    *,
    test_labels: Mapping[str, str],
    train_labels: Mapping[str, str],
    strategy: Literal["random_control", "similarity_component"],
    violation_identity_threshold: Decimal | None,
) -> SimilarityAudit:
    """Summarize all-hit leakage and enforce the grouped strategy threshold."""

    if strategy == "random_control" and violation_identity_threshold is not None:
        raise SimilarityAuditError("random control must not define a hard threshold")
    if strategy == "similarity_component" and violation_identity_threshold not in {
        Decimal("0.70"),
        Decimal("0.50"),
        Decimal("0.30"),
    }:
        raise SimilarityAuditError("grouped audit requires a named fixed threshold")
    if {row.test_accession for row in nearest} != set(test_labels):
        raise SimilarityAuditError("nearest rows do not exactly cover test labels")
    if any(hit.train_accession not in train_labels for hit in hits):
        raise SimilarityAuditError("audit hits do not match train labels")

    violation_hits = (
        ()
        if violation_identity_threshold is None
        else tuple(hit for hit in hits if hit.fident >= violation_identity_threshold)
    )
    if strategy == "similarity_component" and violation_hits:
        raise SimilarityAuditError(
            f"cluster-aware audit found {len(violation_hits)} threshold violation(s)"
        )
    rows: list[AuditedNearestTrain] = []
    for row in sorted(nearest, key=lambda item: item.test_accession):
        train_label = None if row.train_accession is None else train_labels[row.train_accession]
        same_label = None if train_label is None else train_label == test_labels[row.test_accession]
        rows.append(
            AuditedNearestTrain(
                nearest=row,
                test_label=test_labels[row.test_accession],
                train_label=train_label,
                same_label=same_label,
                threshold_violation=(
                    row.fident is not None
                    and violation_identity_threshold is not None
                    and row.fident >= violation_identity_threshold
                ),
            )
        )
    exceedance_counts = {
        format(threshold, ".2f"): sum(hit.fident >= threshold for hit in hits)
        for threshold in (Decimal("0.70"), Decimal("0.50"), Decimal("0.30"))
    }
    flags = Counter(row.same_label for row in rows)
    return SimilarityAudit(
        rows=tuple(rows),
        violation_count=len(violation_hits),
        no_match_count=sum(row.nearest.no_match for row in rows),
        same_label_count=flags[True],
        exceedance_counts=exceedance_counts,
        release_eligible=True,
    )


def serialize_audit(audit: SimilarityAudit) -> SerializedAudit:
    """Serialize one complete nearest-neighbor audit deterministically."""

    rows: list[dict[str, object]] = []
    semantic: list[list[object]] = []
    for audited in audit.rows:
        nearest = audited.nearest
        row: dict[str, object] = {
            "test_accession": nearest.test_accession,
            "test_ec_level_2": audited.test_label,
            "nearest_train_accession": nearest.train_accession,
            "nearest_train_ec_level_2": audited.train_label,
            "fident": nearest.fident,
            "qcov": nearest.qcov,
            "tcov": nearest.tcov,
            "evalue": None if nearest.evalue is None else float(nearest.evalue),
            "bits": None if nearest.bits is None else float(nearest.bits),
            "same_label": audited.same_label,
            "threshold_violation": audited.threshold_violation,
            "no_match": nearest.no_match,
        }
        rows.append(row)
        semantic.append(
            [
                nearest.test_accession,
                audited.test_label,
                nearest.train_accession,
                audited.train_label,
                None if nearest.fident is None else format(nearest.fident, ".6f"),
                None if nearest.qcov is None else format(nearest.qcov, ".6f"),
                None if nearest.tcov is None else format(nearest.tcov, ".6f"),
                None if nearest.evalue is None else str(nearest.evalue.normalize()),
                None if nearest.bits is None else str(nearest.bits.normalize()),
                audited.same_label,
                audited.threshold_violation,
                nearest.no_match,
            ]
        )
    table = pa.Table.from_pylist(rows, schema=AUDIT_MANIFEST_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, row_group_size=65_536, **PARQUET_WRITER_SETTINGS)
    parquet_bytes: bytes = sink.getvalue().to_pybytes()
    semantic_bytes = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in semantic
    ).encode()
    return SerializedAudit(
        parquet_bytes=parquet_bytes,
        file_sha256=sha256_bytes(parquet_bytes),
        semantic_sha256=sha256_bytes(semantic_bytes),
    )


def _logical(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise SimilarityAuditError("shareable audit path is outside the project")
    return resolved.relative_to(root).as_posix()


def _fasta_mapping(path: Path) -> dict[str, tuple[str, str]]:
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise SimilarityAuditError("unable to read strict ASCII cohort FASTA") from error
    if "\r" in text or not text.endswith("\n"):
        raise SimilarityAuditError("cohort FASTA must use LF and end with LF")
    records: dict[str, tuple[str, str]] = {}
    header: str | None = None
    sequence: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            if header is not None:
                accession = header.split("|", 2)[1]
                records[accession] = (header, "".join(sequence))
            header = line
            sequence = []
        elif header is None:
            raise SimilarityAuditError("cohort FASTA sequence precedes header")
        else:
            sequence.append(line)
    if header is not None:
        accession = header.split("|", 2)[1]
        records[accession] = (header, "".join(sequence))
    return records


def _subset_fasta(
    accessions: Sequence[str],
    records: Mapping[str, tuple[str, str]],
) -> bytes:
    lines: list[str] = []
    for accession in sorted(accessions):
        try:
            header, sequence = records[accession]
        except KeyError as error:
            raise SimilarityAuditError("split accession is missing from cohort FASTA") from error
        lines.extend((header, sequence))
    return ("\n".join(lines) + "\n").encode("ascii")


def audit_train_test(
    document: SimilarityConfigDocument,
    *,
    project_root: Path,
) -> SimilarityAuditArtifacts:
    """Run, validate, and publish one independent configured test-to-train audit."""

    config = document.config
    if not isinstance(config, AuditConfig):
        raise SimilarityAuditError("configuration is not an audit operation")
    root = project_root.resolve()
    try:
        split_content_bytes = config.input.split_content_manifest.read_bytes()
        split_content = json.loads(split_content_bytes)
        split_table = pq.read_table(config.input.split_manifest)
        cohort_content_bytes = config.input.cohort_content_manifest.read_bytes()
        cohort_content = CohortContentManifest.model_validate_json(cohort_content_bytes)
        cohort_table = pq.read_table(config.input.cohort_manifest)
    except (OSError, ValueError, pa.ArrowException) as error:
        raise SimilarityAuditError("unable to load audit parents") from error
    if sha256_file(config.input.split_manifest) != split_content.get("artifact", {}).get(
        "file_sha256"
    ):
        raise SimilarityAuditError("split manifest hash mismatch")
    if not split_content.get("release_eligible", False):
        raise SimilarityAuditError("split parent is not release eligible")
    if (
        sha256_file(config.input.cohort_manifest)
        != cohort_content.artifacts.cohort_manifest.file_sha256
    ):
        raise SimilarityAuditError("cohort manifest hash mismatch")
    labels = {str(row["accession"]): str(row["ec_level_2"]) for row in cohort_table.to_pylist()}
    hashes = {
        str(row["accession"]): bytes(row["sequence_sha256"]).hex()
        for row in cohort_table.to_pylist()
    }
    split_rows = split_table.to_pylist()
    train_accessions = tuple(str(row["accession"]) for row in split_rows if row["split"] == "train")
    test_accessions = tuple(str(row["accession"]) for row in split_rows if row["split"] == "test")
    if not train_accessions or not test_accessions:
        raise SimilarityAuditError("audit requires non-empty Train and Test sets")
    records = _fasta_mapping(config.input.cohort_fasta)
    train_fasta = _subset_fasta(train_accessions, records)
    test_fasta = _subset_fasta(test_accessions, records)
    run_path = config.output.run_dir / "provenance.run.json"
    outputs = (
        config.output.train_fasta,
        config.output.test_fasta,
        config.output.audit_manifest,
        config.output.content_manifest,
        config.output.summary,
        run_path,
    )
    run = MmseqsRunContext.create(
        cache_root=config.runtime.cache_root,
        timeout_seconds=config.runtime.timeout_seconds,
        expected_output_names=("audit.tsv",),
        completed_outputs=outputs,
    )
    try:
        run.staging_dir.joinpath("train.fasta").write_bytes(train_fasta)
        run.staging_dir.joinpath("test.fasta").write_bytes(test_fasta)
        argv = build_audit_argv(
            config.search,
            config.runtime,
            len(train_accessions),
            paths=SearchCommandPaths(
                query_fasta=run.staging_dir / "test.fasta",
                target_fasta=run.staging_dir / "train.fasta",
                output_tsv=run.expected_outputs[0],
                temp_dir=run.staging_dir / "tmp",
            ),
        )
        result = run_mmseqs(argv, run)
        test_index = CandidateIndex.from_nodes(
            tuple(SequenceNode(accession, hashes[accession]) for accession in test_accessions)
        )
        train_index = CandidateIndex.from_nodes(
            tuple(SequenceNode(accession, hashes[accession]) for accession in train_accessions)
        )
        hits = parse_search_tsv(result.outputs[0], test_index, train_index)
        nearest = select_nearest_train(test_index, hits)
        audit = audit_observed_hits(
            nearest,
            hits,
            test_labels={accession: labels[accession] for accession in test_accessions},
            train_labels={accession: labels[accession] for accession in train_accessions},
            strategy=config.strategy,
            violation_identity_threshold=(
                None
                if config.violation_identity_threshold is None
                else Decimal(str(config.violation_identity_threshold))
            ),
        )
        serialized = serialize_audit(audit)
        summary = {
            "summary_schema_version": 1,
            "name": config.name,
            "test_count": len(test_accessions),
            "train_count": len(train_accessions),
            "observed_hit_count": len(hits),
            "no_match_count": audit.no_match_count,
            "same_label_nearest_count": audit.same_label_count,
            "threshold_violation_count": audit.violation_count,
            "exceedance_counts": audit.exceedance_counts,
        }
        summary_bytes = serialize_canonical_json(summary)
        git = git_metadata(root)
        reasons: list[str] = []
        if config.run_mode != "freeze":
            reasons.append("development_run_mode")
        if git.dirty is not False:
            reasons.append("generation_git_not_clean")
        if cohort_content.generation_git_dirty is not False:
            reasons.append("cohort_lineage_not_clean")
        content = {
            "manifest_schema_version": 1,
            "operation": "audit",
            "name": config.name,
            "strategy": config.strategy,
            "run_mode": config.run_mode,
            "configuration_file": _logical(document.source_path, root),
            "source_config_sha256": document.source_sha256,
            "effective_config_sha256": document.effective_sha256,
            "split_content_manifest_sha256": sha256_bytes(split_content_bytes),
            "cohort_content_manifest_sha256": sha256_bytes(cohort_content_bytes),
            "cohort_fasta_sha256": sha256_file(config.input.cohort_fasta),
            "violation_identity_threshold": (
                None
                if config.violation_identity_threshold is None
                else f"{config.violation_identity_threshold:.2f}"
            ),
            "mmseqs_version": result.mmseqs_version,
            "command": result.sanitized_argv,
            "counts": summary,
            "artifacts": {
                "audit_manifest": {
                    "logical_path": _logical(config.output.audit_manifest, root),
                    "row_count": len(audit.rows),
                    "file_sha256": serialized.file_sha256,
                    "semantic_sha256": serialized.semantic_sha256,
                },
                "summary": {
                    "logical_path": _logical(config.output.summary, root),
                    "file_sha256": sha256_bytes(summary_bytes),
                },
                "train_fasta_sha256": sha256_bytes(train_fasta),
                "test_fasta_sha256": sha256_bytes(test_fasta),
            },
            "software_version": __version__,
            "generation_git_commit": git.commit,
            "generation_git_dirty": git.dirty,
            "uv_lock_sha256": sha256_file(root / "uv.lock"),
            "release_eligible": not reasons,
            "ineligibility_reasons": reasons,
        }
        content_bytes = serialize_canonical_json(content)
        run_bytes = serialize_canonical_json(
            {
                "run_schema_version": 1,
                "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "staging_dir": str(run.staging_dir),
                "outcome": "success",
            }
        )
        shutil.rmtree(run.staging_dir)
        publish_bundle(
            {
                config.output.train_fasta: train_fasta,
                config.output.test_fasta: test_fasta,
                config.output.audit_manifest: serialized.parquet_bytes,
                config.output.content_manifest: content_bytes,
                config.output.summary: summary_bytes,
                run_path: run_bytes,
            }
        )
    except (OSError, ValueError, PublicationError, pa.ArrowException) as error:
        if isinstance(error, SimilarityAuditError):
            raise
        raise SimilarityAuditError(f"audit generation failed: {error}") from error
    return SimilarityAuditArtifacts(
        audit_manifest_path=config.output.audit_manifest,
        content_manifest_path=config.output.content_manifest,
        summary_path=config.output.summary,
        train_fasta_path=config.output.train_fasta,
        test_fasta_path=config.output.test_fasta,
        content_manifest_sha256=sha256_bytes(content_bytes),
        release_eligible=not reasons,
    )


__all__ = [
    "AUDIT_MANIFEST_SCHEMA",
    "AuditedNearestTrain",
    "NearestTrain",
    "SearchHit",
    "SerializedAudit",
    "SimilarityAudit",
    "SimilarityAuditArtifacts",
    "SimilarityAuditError",
    "audit_observed_hits",
    "audit_train_test",
    "parse_search_tsv",
    "select_nearest_train",
    "serialize_audit",
]
