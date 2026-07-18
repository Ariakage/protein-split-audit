# SPDX-License-Identifier: Apache-2.0

"""Capability-gated frozen Train/Test inputs with delayed Test labels."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from protein_split_audit.attestations.test_access import (
    VerifiedTestAuthorization,
    require_verified_authorization,
)
from protein_split_audit.experiments.schemas import (
    FrozenMethodName,
    FrozenSplitName,
    FrozenTestExperimentConfig,
    FrozenTestSplitInput,
)
from protein_split_audit.features.schemas import ALPHABET
from protein_split_audit.features.validation import (
    load_json_mapping,
    load_selected_fasta,
    nested_manifest_value,
)
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes, sha256_file

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_EXPECTED_TRAIN_COUNT = 308
_EXPECTED_TEST_COUNT = 66


def _verify_hash(path: Path, expected: str, label: str) -> str:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"{label} hash mismatch")
    return observed


@dataclass(frozen=True, slots=True)
class TestSequenceRecord:
    """One verified Train or unlabeled Test sequence."""

    accession: str
    sequence_sha256: bytes
    partition: Literal["train", "test"]
    sequence: str
    bootstrap_component_id: str


@dataclass(frozen=True, slots=True)
class FrozenTestBundle:
    """Hash-bound Train/Test inputs that keep Test targets closed."""

    records: tuple[TestSequenceRecord, ...]
    train_labels: Mapping[str, str]
    label_order: tuple[str, ...]
    input_hashes: Mapping[str, str]
    split_name: FrozenSplitName
    _cohort_manifest: Path = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """Detach and freeze public mappings."""

        object.__setattr__(self, "train_labels", MappingProxyType(dict(self.train_labels)))
        object.__setattr__(self, "input_hashes", MappingProxyType(dict(self.input_hashes)))


class _PredictionIdentity(BaseModel):
    """One immutable unlabeled prediction-row identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accession: str = Field(min_length=1)
    sequence_sha256: Sha256


class _CompletedPredictionManifest(BaseModel):
    """Complete prediction inventory required before Test labels may open."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_version: Literal[1]
    status: Literal["complete"]
    method: FrozenMethodName
    split_name: FrozenSplitName
    evaluation_partition: Literal["test"]
    row_count: Literal[66]
    contains_true_labels: Literal[False]
    inventory: tuple[_PredictionIdentity, ...]
    prediction_artifact: Literal["predictions_unlabeled.parquet"] | None = None
    prediction_artifact_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def require_exact_canonical_inventory(self) -> _CompletedPredictionManifest:
        """Reject duplicate or reordered prediction identities."""

        identities = tuple((item.accession, item.sequence_sha256) for item in self.inventory)
        if len(identities) != self.row_count or len(set(identities)) != self.row_count:
            raise ValueError("prediction inventory must contain 66 unique rows")
        if identities != tuple(sorted(identities)):
            raise ValueError("prediction inventory must be sorted canonically")
        if (self.prediction_artifact is None) != (self.prediction_artifact_sha256 is None):
            raise ValueError("prediction artifact path and hash must be declared together")
        return self


def _read_projection(
    path: Path,
    *,
    columns: list[str],
    filters: list[tuple[str, str, object]],
    label: str,
) -> list[dict[str, object]]:
    try:
        rows = pq.read_table(path, columns=columns, filters=filters).to_pylist()
    except (OSError, KeyError, pa.ArrowException) as error:
        raise ValueError(f"unable to read {label} projection") from error
    return cast(list[dict[str, object]], rows)


def _verify_complete_inputs(
    config: FrozenTestExperimentConfig,
    split_name: FrozenSplitName,
) -> tuple[dict[str, str], FrozenTestSplitInput]:
    try:
        split = next(item for item in config.splits if item.name == split_name)
    except StopIteration as error:
        raise ValueError(f"unknown frozen split: {split_name}") from error

    hashes = {
        "cohort_manifest_sha256": _verify_hash(
            config.cohort.manifest,
            config.cohort.file_sha256,
            "cohort manifest",
        ),
        "cohort_content_manifest_sha256": _verify_hash(
            config.cohort.content_manifest,
            config.cohort.content_manifest_sha256,
            "cohort content manifest",
        ),
        "cohort_fasta_sha256": _verify_hash(
            config.cohort.fasta,
            config.cohort.fasta_sha256,
            "cohort FASTA",
        ),
        "split_manifest_sha256": _verify_hash(
            split.manifest,
            split.file_sha256,
            "split manifest",
        ),
        "split_content_manifest_sha256": _verify_hash(
            split.content_manifest,
            split.content_manifest_sha256,
            "split content manifest",
        ),
    }
    return hashes, split


def _validate_content_manifests(
    config: FrozenTestExperimentConfig,
    split: FrozenTestSplitInput,
    hashes: Mapping[str, str],
) -> tuple[str, ...]:
    cohort_content = load_json_mapping(config.cohort.content_manifest)
    split_content = load_json_mapping(split.content_manifest)
    if (
        nested_manifest_value(cohort_content, "artifacts", "cohort_manifest", "file_sha256")
        != hashes["cohort_manifest_sha256"]
    ):
        raise ValueError("cohort content manifest artifact hash mismatch")
    if (
        nested_manifest_value(cohort_content, "artifacts", "fasta", "file_sha256")
        != hashes["cohort_fasta_sha256"]
    ):
        raise ValueError("cohort content manifest FASTA hash mismatch")
    if (
        nested_manifest_value(split_content, "artifact", "file_sha256")
        != hashes["split_manifest_sha256"]
    ):
        raise ValueError("split content manifest artifact hash mismatch")
    if (
        split_content.get("cohort_content_manifest_sha256")
        != hashes["cohort_content_manifest_sha256"]
    ):
        raise ValueError("split parent cohort content hash mismatch")

    labels = cohort_content.get("selected_labels")
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("cohort content manifest has invalid selected_labels")
    label_order = tuple(labels)
    if label_order != config.evaluation.label_order:
        raise ValueError("cohort label order differs from the frozen Test configuration")
    return label_order


def _load_assignments(
    split_manifest: Path,
) -> dict[str, dict[str, object]]:
    rows = _read_projection(
        split_manifest,
        columns=["accession", "sequence_sha256", "split"],
        filters=[("split", "in", ["train", "test"])],
        label="Train/Test split assignment",
    )
    accessions = [str(row["accession"]) for row in rows]
    if len(accessions) != len(set(accessions)):
        raise ValueError("frozen Train/Test split contains duplicate accessions")
    by_accession = {str(row["accession"]): row for row in rows}
    counts = {
        partition: sum(str(row["split"]) == partition for row in rows)
        for partition in ("train", "test")
    }
    if counts != {"train": _EXPECTED_TRAIN_COUNT, "test": _EXPECTED_TEST_COUNT}:
        raise ValueError("frozen split must contain exactly 308 Train and 66 Test records")
    return by_accession


def _component_inventory_hash(records: list[TestSequenceRecord]) -> str:
    rows: list[object] = [
        {
            "accession": record.accession,
            "bootstrap_component_id": record.bootstrap_component_id,
        }
        for record in records
        if record.partition == "test"
    ]
    payload: dict[str, object] = {
        "schema_version": 1,
        "source_column": "discovery_component_id_cluster30",
        "rows": rows,
    }
    return sha256_bytes(serialize_canonical_json(payload))


def load_frozen_test_bundle(
    config: FrozenTestExperimentConfig,
    split_name: FrozenSplitName,
    authorization: VerifiedTestAuthorization,
) -> FrozenTestBundle:
    """Load exact Train/Test sequences while keeping Test labels inaccessible."""

    require_verified_authorization(authorization)
    hashes, split = _verify_complete_inputs(config, split_name)
    label_order = _validate_content_manifests(config, split, hashes)

    assignments = _load_assignments(split.manifest)
    selected = frozenset(assignments)
    cohort_rows = _read_projection(
        config.cohort.manifest,
        columns=[
            "accession",
            "sequence_sha256",
            "sequence_length",
            "discovery_component_id_cluster30",
        ],
        filters=[("accession", "in", sorted(selected))],
        label="unlabeled cohort sequence",
    )
    cohort_accessions = [str(row["accession"]) for row in cohort_rows]
    if len(cohort_accessions) != len(set(cohort_accessions)):
        raise ValueError("selected cohort projection contains duplicate accessions")
    cohort_by_accession = {str(row["accession"]): row for row in cohort_rows}
    if set(cohort_by_accession) != selected:
        raise ValueError("selected split and cohort accessions differ")

    fasta_sequences = load_selected_fasta(config.cohort.fasta, selected)
    if set(fasta_sequences) != selected:
        raise ValueError("selected cohort and FASTA accessions differ")

    allowed = frozenset(ALPHABET)
    records: list[TestSequenceRecord] = []
    for accession in sorted(selected):
        cohort_row = cohort_by_accession[accession]
        assignment = assignments[accession]
        partition_value = assignment["split"]
        if partition_value not in {"train", "test"}:
            raise ValueError(f"invalid frozen partition: {accession}")
        partition: Literal["train", "test"] = partition_value
        sequence = fasta_sequences[accession]
        if not sequence or not set(sequence).issubset(allowed):
            raise ValueError(f"selected sequence is invalid: {accession}")
        digest_bytes = bytes.fromhex(sha256_bytes(sequence.encode("ascii")))
        if digest_bytes != cohort_row["sequence_sha256"]:
            raise ValueError(f"selected sequence hash mismatch: {accession}")
        if digest_bytes != assignment["sequence_sha256"]:
            raise ValueError(f"split sequence hash mismatch: {accession}")
        if len(sequence) != cohort_row["sequence_length"]:
            raise ValueError(f"selected sequence length mismatch: {accession}")
        component = cohort_row[config.cohort.bootstrap_component_column]
        if (
            not isinstance(component, str)
            or not component.strip()
            or component.strip().casefold() in {"unknown", "none", "na", "n/a"}
        ):
            raise ValueError(f"invalid frozen bootstrap component: {accession}")
        records.append(
            TestSequenceRecord(
                accession=accession,
                sequence_sha256=digest_bytes,
                partition=partition,
                sequence=sequence,
                bootstrap_component_id=component,
            )
        )

    train_accessions = sorted(row.accession for row in records if row.partition == "train")
    train_rows = _read_projection(
        config.cohort.manifest,
        columns=["accession", "ec_level_2"],
        filters=[("accession", "in", train_accessions)],
        label="Train target",
    )
    train_row_accessions = [str(row["accession"]) for row in train_rows]
    if len(train_row_accessions) != len(set(train_row_accessions)):
        raise ValueError("Train target projection contains duplicate accessions")
    if set(train_row_accessions) != set(train_accessions):
        raise ValueError("Train target projection differs from Train assignments")
    train_labels: dict[str, str] = {}
    for row in train_rows:
        accession = str(row["accession"])
        label = row["ec_level_2"]
        if not isinstance(label, str) or label not in label_order:
            raise ValueError(f"Train target is outside the frozen label set: {accession}")
        train_labels[accession] = label

    hashes["test_component_inventory_sha256"] = _component_inventory_hash(records)
    return FrozenTestBundle(
        records=tuple(records),
        train_labels=train_labels,
        label_order=label_order,
        input_hashes=hashes,
        split_name=split_name,
        _cohort_manifest=config.cohort.manifest,
    )


def load_test_labels_after_predictions(
    bundle: FrozenTestBundle,
    prediction_manifest: Path,
    authorization: VerifiedTestAuthorization,
) -> Mapping[str, str]:
    """Open Test labels only after validating a complete unlabeled inventory."""

    require_verified_authorization(authorization)
    try:
        manifest = _CompletedPredictionManifest.model_validate(
            load_json_mapping(prediction_manifest)
        )
    except ValidationError as error:
        raise ValueError("invalid completed prediction manifest") from error
    if manifest.split_name != bundle.split_name:
        raise ValueError("prediction manifest split differs from the frozen input bundle")

    if manifest.prediction_artifact is not None:
        artifact = prediction_manifest.parent / manifest.prediction_artifact
        if sha256_file(artifact) != manifest.prediction_artifact_sha256:
            raise ValueError("sealed prediction artifact hash mismatch")
        try:
            prediction_table = pq.read_table(artifact)
        except (OSError, pa.ArrowException) as error:
            raise ValueError("unable to read sealed prediction artifact") from error
        forbidden = {"true_label", "label", "correct"}
        if forbidden.intersection(prediction_table.column_names):
            raise ValueError("sealed prediction artifact contains Test targets")
        identities = tuple(
            (str(row["accession"]), bytes(row["sequence_sha256"]).hex())
            for row in prediction_table.select(["accession", "sequence_sha256"]).to_pylist()
        )
        if identities != tuple(
            (item.accession, item.sequence_sha256) for item in manifest.inventory
        ):
            raise ValueError("sealed prediction artifact inventory mismatch")

    expected = tuple(
        (record.accession, record.sequence_sha256.hex())
        for record in bundle.records
        if record.partition == "test"
    )
    observed = tuple((item.accession, item.sequence_sha256) for item in manifest.inventory)
    if observed != expected:
        raise ValueError("prediction inventory differs from the frozen Test inventory")

    test_accessions = [accession for accession, _digest in expected]
    rows = _read_projection(
        bundle._cohort_manifest,
        columns=["accession", "ec_level_2"],
        filters=[("accession", "in", test_accessions)],
        label="delayed Test target",
    )
    accessions = [str(row["accession"]) for row in rows]
    if len(accessions) != len(set(accessions)) or set(accessions) != set(test_accessions):
        raise ValueError("Test target projection differs from the prediction inventory")
    labels: dict[str, str] = {}
    for row in rows:
        accession = str(row["accession"])
        label = row["ec_level_2"]
        if not isinstance(label, str) or label not in bundle.label_order:
            raise ValueError(f"Test target is outside the frozen label set: {accession}")
        labels[accession] = label
    return MappingProxyType(labels)


__all__ = [
    "FrozenTestBundle",
    "TestSequenceRecord",
    "load_frozen_test_bundle",
    "load_test_labels_after_predictions",
]
