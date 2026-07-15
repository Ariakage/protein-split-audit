# SPDX-License-Identifier: Apache-2.0

"""Standalone Train-only baseline fitting from an immutable feature cache."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.config import load_model_config
from protein_split_audit.features.cache import load_feature_cache
from protein_split_audit.features.schemas import FeatureConfig
from protein_split_audit.features.validation import SequenceRecord, ValidatedInputBundle
from protein_split_audit.models.logistic_regression import train_logistic
from protein_split_audit.models.majority import fit_majority
from protein_split_audit.models.schemas import (
    LogisticRegressionModelConfig,
    MajorityModelConfig,
)
from protein_split_audit.models.serialization import save_model
from protein_split_audit.provenance import sha256_file


@dataclass(frozen=True, slots=True)
class StandaloneTrainingResult:
    """Artifacts from one Train-only low-level fit."""

    model_path: Path
    manifest_path: Path


def _mapping(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON manifest: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON manifest must be a mapping: {path.name}")
    return value


def _required_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ValueError(f"feature cache identity missing {key}")
    return value


def _load_bound_cache(
    feature_manifest: Path,
    split_manifest: Path,
    split_content_manifest: Path,
) -> tuple[object, tuple[SequenceRecord, ...], tuple[str, ...], FeatureConfig]:
    feature_mapping = _mapping(feature_manifest)
    identity = feature_mapping.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("feature cache manifest has no identity")
    split_content = _mapping(split_content_manifest)
    artifact = split_content.get("artifact")
    expected_split_hash = artifact.get("file_sha256") if isinstance(artifact, dict) else None
    if expected_split_hash != sha256_file(split_manifest):
        raise ValueError("split manifest hash mismatch")
    if _required_string(identity, "split_manifest_sha256") != expected_split_hash:
        raise ValueError("feature cache and split manifest disagree")
    if _required_string(identity, "split_content_manifest_sha256") != sha256_file(
        split_content_manifest
    ):
        raise ValueError("feature cache and split content manifest disagree")
    feature_raw = identity.get("feature")
    config = FeatureConfig.model_validate(feature_raw)
    accessions_raw = identity.get("accessions")
    labels_raw = identity.get("label_order")
    if not isinstance(accessions_raw, list) or not all(
        isinstance(value, str) for value in accessions_raw
    ):
        raise ValueError("feature cache identity has invalid accessions")
    if not isinstance(labels_raw, list) or not all(isinstance(value, str) for value in labels_raw):
        raise ValueError("feature cache identity has invalid label order")
    rows = pq.read_table(
        split_manifest,
        columns=["accession", "sequence_sha256", "ec_level_2", "split"],
    ).to_pylist()
    selected = {
        str(row["accession"]): row for row in rows if row["split"] in {"train", "validation"}
    }
    if set(selected) != set(accessions_raw):
        raise ValueError("feature cache and selected split accessions disagree")
    records = tuple(
        SequenceRecord(
            accession=accession,
            sequence_sha256=bytes(selected[accession]["sequence_sha256"]),
            label=str(selected[accession]["ec_level_2"]),
            split=str(selected[accession]["split"]),
            sequence="",
        )
        for accession in accessions_raw
    )
    bundle = ValidatedInputBundle(
        records=records,
        label_order=tuple(labels_raw),
        cohort_manifest_sha256=_required_string(identity, "cohort_manifest_sha256"),
        cohort_content_manifest_sha256=_required_string(identity, "cohort_content_manifest_sha256"),
        cohort_fasta_sha256=_required_string(identity, "cohort_fasta_sha256"),
        split_manifest_sha256=_required_string(identity, "split_manifest_sha256"),
        split_content_manifest_sha256=_required_string(identity, "split_content_manifest_sha256"),
    )
    cache = load_feature_cache(feature_manifest.parent, config, bundle)
    return cache.matrix, records, bundle.label_order, config


def train_cached_model(
    *,
    feature_manifest: Path,
    split_manifest: Path,
    split_content_manifest: Path,
    config_path: Path,
    output_dir: Path,
) -> StandaloneTrainingResult:
    """Fit Majority or Logistic Regression using Train labels only."""

    if output_dir.exists():
        raise FileExistsError(f"model output already exists: {output_dir}")
    matrix, records, label_order, feature_config = _load_bound_cache(
        feature_manifest, split_manifest, split_content_manifest
    )
    model_config = load_model_config(config_path)
    if not isinstance(model_config, (LogisticRegressionModelConfig, MajorityModelConfig)):
        raise ValueError("standalone model train does not run Nearest Homolog")
    output_dir.mkdir(parents=True)
    if isinstance(model_config, LogisticRegressionModelConfig):
        trained = train_logistic(matrix, records, label_order, feature_config, model_config)
        model_path = save_model(output_dir / "model.joblib", trained)
    elif isinstance(model_config, MajorityModelConfig):
        majority = fit_majority([row.label for row in records if row.split == "train"])
        model_path = output_dir / "model.json"
        model_path.write_text(
            json.dumps(
                {"counts": list(majority.counts), "label": majority.label},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    manifest_path = output_dir / "training_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "configuration_sha256": sha256_file(config_path),
                "feature_manifest_sha256": sha256_file(feature_manifest),
                "label_order": list(label_order),
                "model_file": model_path.name,
                "model_file_sha256": sha256_file(model_path),
                "split_content_manifest_sha256": sha256_file(split_content_manifest),
                "split_manifest_sha256": sha256_file(split_manifest),
                "train_count": sum(row.split == "train" for row in records),
                "training_split": "train",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return StandaloneTrainingResult(model_path, manifest_path)


__all__ = ["StandaloneTrainingResult", "train_cached_model"]
