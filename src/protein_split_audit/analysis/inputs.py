# SPDX-License-Identifier: Apache-2.0

"""Strict parsing and private alignment of frozen v0.5 prediction outputs."""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.analysis.schemas import (
    LABEL_ORDER,
    METHODS,
    SPLITS,
    MethodName,
    PostTestAnalysisConfig,
    SplitName,
)

_SCORE_COLUMNS = tuple(f"score_{label.replace('.', '_')}" for label in LABEL_ORDER)
PREDICTION_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string()),
        pa.field("sequence_sha256", pa.binary(32)),
        pa.field("split_name", pa.string()),
        pa.field("evaluation_split", pa.string()),
        pa.field("true_label", pa.string()),
        pa.field("predicted_label", pa.string()),
        pa.field("correct", pa.bool_()),
        *(pa.field(name, pa.float64()) for name in _SCORE_COLUMNS),
        pa.field("nearest_train_identity", pa.float64()),
        pa.field("no_hit", pa.bool_()),
    ]
)
COHORT_METADATA_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence_sha256", pa.binary(32), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("sequence_length", pa.uint32(), nullable=False),
        pa.field("organism_id", pa.uint64(), nullable=False),
        pa.field("discovery_component_id_cluster30", pa.string(), nullable=False),
        pa.field("source_dataset_manifest", pa.string(), nullable=False),
        pa.field("source_dataset_manifest_sha256", pa.binary(32), nullable=False),
        pa.field("cohort_version", pa.string(), nullable=False),
        pa.field("selection_rule_version", pa.string(), nullable=False),
    ]
)
SPLIT_METADATA_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence_sha256", pa.binary(32), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
        pa.field("similarity_component_id", pa.string(), nullable=True),
        pa.field("split_name", pa.string(), nullable=False),
        pa.field("strategy", pa.string(), nullable=False),
        pa.field("seed", pa.int64(), nullable=False),
    ]
)
NEAREST_DETAIL_SCHEMA = pa.schema(
    [
        pa.field("query_accession", pa.string()),
        pa.field("nearest_train_accession", pa.string()),
        pa.field("nearest_train_label", pa.string()),
        pa.field("predicted_label", pa.string()),
        pa.field("percent_identity", pa.float64()),
        pa.field("query_coverage", pa.float64()),
        pa.field("target_coverage", pa.float64()),
        pa.field("bitscore", pa.float64()),
        pa.field("evalue", pa.float64()),
        pa.field("no_hit", pa.bool_()),
    ]
)


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """One private prediction row without a sequence or model object."""

    accession: str
    sequence_sha256: bytes
    split_name: SplitName
    method: MethodName
    true_label: str
    predicted_label: str
    correct: bool
    nearest_train_identity: float | None
    no_hit: bool | None

    @property
    def private_identity(self) -> tuple[str, bytes]:
        return self.accession, self.sequence_sha256


@dataclass(frozen=True, slots=True)
class AnalysisRow:
    """One private, sequence-free row used by deterministic analysis code."""

    accession: str
    sequence_sha256: bytes
    split_name: SplitName
    method: MethodName
    true_label: str
    predicted_label: str
    correct: bool
    sequence_length: int
    component_id: str
    component_size: int
    nearest_train_identity: float | None
    no_hit: bool
    nearest_train_accession: str | None = None
    nearest_train_label: str | None = None
    query_coverage: float | None = None
    target_coverage: float | None = None
    bitscore: float | None = None
    evalue: float | None = None

    @property
    def private_identity(self) -> tuple[str, bytes]:
        return self.accession, self.sequence_sha256


@dataclass(frozen=True, slots=True)
class _CohortRow:
    accession: str
    sequence_sha256: bytes
    label: str
    length: int
    component_id: str
    component_size: int


@dataclass(frozen=True, slots=True)
class _NearestDetail:
    query_accession: str
    nearest_train_accession: str | None
    nearest_train_label: str | None
    predicted_label: str
    percent_identity: float | None
    query_coverage: float | None
    target_coverage: float | None
    bitscore: float | None
    evalue: float | None
    no_hit: bool


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    raise ValueError("prediction sequence hash must be fixed-size binary")


def parse_prediction_artifact(
    path: Path,
    method: MethodName,
    split: SplitName,
    *,
    expected_count: int = 66,
) -> tuple[PredictionRecord, ...]:
    """Parse one exact-schema prediction table and validate safe row invariants."""

    parquet = pq.ParquetFile(path)
    if not parquet.schema_arrow.equals(PREDICTION_SCHEMA, check_metadata=False):
        raise ValueError("frozen prediction Parquet schema or column order is invalid")
    if parquet.metadata.num_rows != expected_count:
        raise ValueError("frozen prediction row count is invalid")
    table = parquet.read()
    rows: list[PredictionRecord] = []
    seen_accessions: set[str] = set()
    seen_hashes: set[bytes] = set()
    for raw in table.to_pylist():
        accession = raw["accession"]
        digest = _as_bytes(raw["sequence_sha256"])
        if not isinstance(accession, str) or not accession or len(digest) != 32:
            raise ValueError("prediction private row identity is invalid")
        if accession in seen_accessions or digest in seen_hashes:
            raise ValueError("prediction artifact contains a duplicate private row identity")
        seen_accessions.add(accession)
        seen_hashes.add(digest)
        if raw["split_name"] != split or raw["evaluation_split"] != "test":
            raise ValueError("prediction split identity is invalid")
        true_label = raw["true_label"]
        predicted_label = raw["predicted_label"]
        if true_label not in LABEL_ORDER or predicted_label not in LABEL_ORDER:
            raise ValueError("prediction label is outside the frozen label order")
        correct = raw["correct"]
        if not isinstance(correct, bool) or correct != (true_label == predicted_label):
            raise ValueError("prediction correct flag disagrees with its labels")
        for column in _SCORE_COLUMNS:
            score = raw[column]
            if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise ValueError("prediction score must be finite")
        no_hit = raw["no_hit"]
        nearest = raw["nearest_train_identity"]
        if method == "nearest-homolog":
            if not isinstance(no_hit, bool):
                raise ValueError("prediction no-hit flag must be boolean")
            if no_hit:
                if nearest is not None:
                    raise ValueError("prediction no-hit identity must be null")
                normalized_identity = None
            else:
                if not isinstance(nearest, (int, float)) or not math.isfinite(float(nearest)):
                    raise ValueError("prediction hit identity must be finite")
                normalized_identity = float(nearest)
                if not 0.0 <= normalized_identity <= 1.0:
                    raise ValueError("prediction hit identity must be between zero and one")
        else:
            if no_hit is not None or nearest is not None:
                raise ValueError(
                    "prediction neighbor metadata must be null for non-Nearest-Homolog methods"
                )
            normalized_identity = None
        rows.append(
            PredictionRecord(
                accession=accession,
                sequence_sha256=digest,
                split_name=split,
                method=method,
                true_label=true_label,
                predicted_label=predicted_label,
                correct=correct,
                nearest_train_identity=normalized_identity,
                no_hit=no_hit,
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.accession, item.sequence_sha256)))


def align_prediction_inventories(
    rows_by_method: Mapping[MethodName, tuple[PredictionRecord, ...]],
) -> tuple[tuple[str, bytes], ...]:
    """Require methods in one split to describe the identical private Test rows."""

    if not rows_by_method:
        raise ValueError("prediction alignment requires at least one method")
    reference: tuple[tuple[str, bytes, str], ...] | None = None
    identities: tuple[tuple[str, bytes], ...] = ()
    for method in sorted(rows_by_method):
        rows = rows_by_method[method]
        observed = tuple(
            (
                row.accession,
                row.sequence_sha256,
                row.true_label,
            )
            for row in rows
        )
        if reference is None:
            reference = observed
            identities = tuple((row.accession, row.sequence_sha256) for row in rows)
        elif observed != reference:
            raise ValueError("methods must have an identical private row inventory")
    return identities


def _require_schema(path: Path, schema: pa.Schema, *, artifact: str, rows: int) -> pa.Table:
    parquet = pq.ParquetFile(path)
    if not parquet.schema_arrow.equals(schema, check_metadata=False):
        raise ValueError(f"{artifact} Parquet schema or column order is invalid")
    if parquet.metadata.num_rows != rows:
        raise ValueError(f"{artifact} row count is invalid")
    return parquet.read()


def _load_cohort(config: PostTestAnalysisConfig) -> dict[tuple[str, bytes], _CohortRow]:
    table = _require_schema(
        config.inputs.cohort.manifest,
        COHORT_METADATA_SCHEMA,
        artifact="cohort metadata",
        rows=442,
    )
    raw_rows = table.to_pylist()
    component_counts: dict[str, int] = {}
    for raw in raw_rows:
        component = raw["discovery_component_id_cluster30"]
        if not isinstance(component, str) or not component.strip():
            raise ValueError("cohort metadata has an invalid Cluster30 component count")
        component_counts[component] = component_counts.get(component, 0) + 1
    output: dict[tuple[str, bytes], _CohortRow] = {}
    seen_accessions: set[str] = set()
    seen_hashes: set[bytes] = set()
    for raw in raw_rows:
        accession = raw["accession"]
        digest = _as_bytes(raw["sequence_sha256"])
        label = raw["ec_level_2"]
        length = raw["sequence_length"]
        component = raw["discovery_component_id_cluster30"]
        if (
            not isinstance(accession, str)
            or not accession
            or len(digest) != 32
            or label not in LABEL_ORDER
            or isinstance(length, bool)
            or not isinstance(length, int)
            or not 50 <= length <= 1000
        ):
            raise ValueError("cohort metadata contains an invalid private row")
        if accession in seen_accessions or digest in seen_hashes:
            raise ValueError("cohort metadata contains a duplicate private row")
        seen_accessions.add(accession)
        seen_hashes.add(digest)
        output[(accession, digest)] = _CohortRow(
            accession,
            digest,
            label,
            length,
            component,
            component_counts[component],
        )
    return output


def _load_split_test_rows(
    config: PostTestAnalysisConfig,
    cohort: Mapping[tuple[str, bytes], _CohortRow],
) -> dict[SplitName, dict[tuple[str, bytes], _CohortRow]]:
    output: dict[SplitName, dict[tuple[str, bytes], _CohortRow]] = {}
    for identity in config.inputs.splits:
        table = _require_schema(
            identity.manifest,
            SPLIT_METADATA_SCHEMA,
            artifact=f"{identity.name} split metadata",
            rows=442,
        )
        counts = {"train": 0, "validation": 0, "test": 0}
        test_rows: dict[tuple[str, bytes], _CohortRow] = {}
        all_rows: set[tuple[str, bytes]] = set()
        for raw in table.to_pylist():
            accession = raw["accession"]
            digest = _as_bytes(raw["sequence_sha256"])
            key = (accession, digest)
            partition = raw["split"]
            if raw["split_name"] != identity.name or partition not in counts:
                raise ValueError(f"{identity.name} split metadata has an invalid partition")
            if key in all_rows or key not in cohort:
                raise ValueError(f"{identity.name} split metadata has a private join mismatch")
            all_rows.add(key)
            member = cohort[key]
            if raw["ec_level_2"] != member.label:
                raise ValueError(f"{identity.name} split metadata has an aggregate label mismatch")
            counts[partition] += 1
            if partition == "test":
                test_rows[key] = member
        if counts != {"train": 308, "validation": 68, "test": 66} or len(all_rows) != 442:
            raise ValueError(f"{identity.name} split metadata partition counts are invalid")
        output[identity.name] = test_rows
    if tuple(output) != SPLITS:
        raise ValueError("split metadata inventory is incomplete")
    return output


def _optional_finite(raw: object, *, field: str) -> float | None:
    if raw is None:
        return None
    if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise ValueError(f"nearest-homolog {field} must be finite when present")
    return float(raw)


def parse_nearest_detail(path: Path, split: SplitName) -> tuple[_NearestDetail, ...]:
    """Parse one exact Nearest Homolog detail table without exposing row identity."""

    table = _require_schema(
        path,
        NEAREST_DETAIL_SCHEMA,
        artifact=f"{split} nearest-homolog detail",
        rows=66,
    )
    rows: list[_NearestDetail] = []
    seen: set[str] = set()
    for raw in table.to_pylist():
        query = raw["query_accession"]
        predicted = raw["predicted_label"]
        no_hit = raw["no_hit"]
        if (
            not isinstance(query, str)
            or not query
            or query in seen
            or predicted not in LABEL_ORDER
            or not isinstance(no_hit, bool)
        ):
            raise ValueError(f"{split} nearest-homolog detail has an invalid row identity")
        seen.add(query)
        row = _NearestDetail(
            query_accession=query,
            nearest_train_accession=raw["nearest_train_accession"],
            nearest_train_label=raw["nearest_train_label"],
            predicted_label=predicted,
            percent_identity=_optional_finite(raw["percent_identity"], field="identity"),
            query_coverage=_optional_finite(raw["query_coverage"], field="query coverage"),
            target_coverage=_optional_finite(raw["target_coverage"], field="target coverage"),
            bitscore=_optional_finite(raw["bitscore"], field="bitscore"),
            evalue=_optional_finite(raw["evalue"], field="e-value"),
            no_hit=no_hit,
        )
        neighbor_values = (
            row.nearest_train_accession,
            row.nearest_train_label,
            row.percent_identity,
            row.query_coverage,
            row.target_coverage,
            row.bitscore,
            row.evalue,
        )
        if no_hit and any(value is not None for value in neighbor_values):
            raise ValueError(f"{split} nearest-homolog no-hit metadata is inconsistent")
        if not no_hit and any(value is None for value in neighbor_values):
            raise ValueError(f"{split} nearest-homolog hit metadata is incomplete")
        rows.append(row)
    return tuple(sorted(rows, key=lambda item: item.query_accession))


def load_frozen_analysis_rows(
    config: PostTestAnalysisConfig,
    authorization: object,
) -> tuple[AnalysisRow, ...]:
    """Load only authenticated frozen outputs and sequence-free join metadata."""

    from protein_split_audit.analysis.authorization import (  # local to keep schemas acyclic
        require_verified_analysis_authorization,
    )

    require_verified_analysis_authorization(authorization)
    cohort = _load_cohort(config)
    test_rows = _load_split_test_rows(config, cohort)
    details: dict[SplitName, dict[str, _NearestDetail]] = {}
    for nearest_artifact in config.inputs.nearest_homolog.artifacts:
        parsed = parse_nearest_detail(
            config.inputs.run_a.root / nearest_artifact.relative_path,
            nearest_artifact.split,
        )
        details[nearest_artifact.split] = {row.query_accession: row for row in parsed}
    output: list[AnalysisRow] = []
    per_split: dict[SplitName, dict[MethodName, tuple[PredictionRecord, ...]]] = {
        split: {} for split in SPLITS
    }
    for prediction_artifact in config.inputs.predictions.artifacts:
        path = config.inputs.run_a.root / prediction_artifact.relative_path
        rows = parse_prediction_artifact(
            path,
            prediction_artifact.method,
            prediction_artifact.split,
        )
        per_split[prediction_artifact.split][prediction_artifact.method] = rows
    for split in SPLITS:
        if tuple(per_split[split]) != METHODS:
            raise ValueError(f"{split} prediction method inventory is incomplete")
        align_prediction_inventories(per_split[split])
        expected = test_rows[split]
        for method in METHODS:
            predictions = per_split[split][method]
            observed = {row.private_identity for row in predictions}
            if observed != set(expected):
                raise ValueError(f"{split} prediction-to-metadata private join is incomplete")
            if set(details[split]) != {row.accession for row in predictions}:
                raise ValueError(f"{split} nearest-homolog private join is incomplete")
            for prediction in predictions:
                metadata = expected[prediction.private_identity]
                detail = details[split][prediction.accession]
                if prediction.true_label != metadata.label:
                    raise ValueError(f"{split} prediction metadata relation is inconsistent")
                if method == "nearest-homolog" and (
                    prediction.nearest_train_identity != detail.percent_identity
                    or prediction.no_hit != detail.no_hit
                    or prediction.predicted_label != detail.predicted_label
                ):
                    raise ValueError(f"{split} nearest-homolog prediction relation is inconsistent")
                output.append(
                    AnalysisRow(
                        accession=prediction.accession,
                        sequence_sha256=prediction.sequence_sha256,
                        split_name=split,
                        method=method,
                        true_label=prediction.true_label,
                        predicted_label=prediction.predicted_label,
                        correct=prediction.correct,
                        sequence_length=metadata.length,
                        component_id=metadata.component_id,
                        component_size=metadata.component_size,
                        nearest_train_identity=detail.percent_identity,
                        no_hit=detail.no_hit,
                        nearest_train_accession=detail.nearest_train_accession,
                        nearest_train_label=detail.nearest_train_label,
                        query_coverage=detail.query_coverage,
                        target_coverage=detail.target_coverage,
                        bitscore=detail.bitscore,
                        evalue=detail.evalue,
                    )
                )
    result = tuple(output)
    verify_v050_aggregate_regression(result, config.inputs.reviewed_aggregate.root)
    return result


def verify_v050_aggregate_regression(
    rows: Sequence[AnalysisRow],
    aggregate_root: Path,
) -> None:
    """Recompute released v0.5 point metrics as an input-regression gate."""

    from protein_split_audit.analysis.stratified_metrics import metric_value

    path = aggregate_root / "test_summary.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        published = tuple(csv.DictReader(handle))
    if len(published) != len(METHODS) * len(SPLITS):
        raise ValueError("reviewed v0.5 aggregate cell count is invalid")
    index = {(item["split"], item["method"]): item for item in published}
    if len(index) != len(published):
        raise ValueError("reviewed v0.5 aggregate contains a duplicate cell")
    records = tuple(rows)
    for method in METHODS:
        for split in SPLITS:
            members = tuple(
                row for row in records if row.method == method and row.split_name == split
            )
            published_method = method.replace("-", "_")
            expected = index.get((split, published_method))
            if expected is None or len(members) != 66 or expected.get("support") != "66":
                raise ValueError("reviewed v0.5 aggregate inventory is inconsistent")
            for metric in ("accuracy", "balanced_accuracy", "macro_f1"):
                observed = metric_value(members, metric)
                try:
                    recorded = float(expected[metric])
                except (KeyError, TypeError, ValueError):
                    raise ValueError("reviewed v0.5 aggregate metric is invalid") from None
                if not math.isclose(observed, recorded, rel_tol=0.0, abs_tol=1e-15):
                    raise ValueError("recomputed v0.5 aggregate metric does not match release")


__all__ = [
    "COHORT_METADATA_SCHEMA",
    "NEAREST_DETAIL_SCHEMA",
    "PREDICTION_SCHEMA",
    "SPLIT_METADATA_SCHEMA",
    "AnalysisRow",
    "PredictionRecord",
    "align_prediction_inventories",
    "load_frozen_analysis_rows",
    "parse_nearest_detail",
    "parse_prediction_artifact",
    "verify_v050_aggregate_regression",
]
