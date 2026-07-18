# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import protein_split_audit.attestations.test_access as access_module
from protein_split_audit.attestations.test_access import (
    RealTestAccessDenied,
    VerifiedTestAuthorization,
)
from protein_split_audit.config import load_experiment_config
from protein_split_audit.evaluation.test_inputs import (
    FrozenTestBundle,
    load_frozen_test_bundle,
    load_test_labels_after_predictions,
)
from protein_split_audit.experiments.schemas import FrozenTestExperimentConfig
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE_CONFIG = PROJECT_ROOT / "configs/experiment/v050-test.yaml"
LABEL_ORDER = ("2.7", "3.1", "1.1", "2.1", "4.1")
ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def _sequence(index: int) -> str:
    digits: list[str] = []
    value = index
    for _ in range(6):
        digits.append(ALPHABET[value % len(ALPHABET)])
        value //= len(ALPHABET)
    return "A" * 44 + "".join(reversed(digits))


def _authorization() -> VerifiedTestAuthorization:
    return VerifiedTestAuthorization(
        attestation_path=Path("docs/attestations/v0.5.0-test-freeze.yaml"),
        attestation_sha256="a" * 64,
        generation_commit="b" * 40,
        execution_commit="c" * 40,
        approval_reference=(
            "https://github.com/Ariakage/protein-split-audit/pull/3#issuecomment-5000000000"
        ),
        allowed_sessions=("run-a", "run-b"),
        protocol_sha256="d" * 64,
        config_sha256="e" * 64,
        lock_sha256="f" * 64,
        dependency_diff_sha256="0" * 64,
        frozen_hashes={},
        _token=access_module._CAPABILITY_TOKEN,
    )


def _write_inputs(
    root: Path,
    *,
    blank_test_component: bool = False,
) -> FrozenTestExperimentConfig:
    data = root / "data"
    data.mkdir(parents=True)
    accessions = [f"P{index:04d}" for index in range(442)]
    sequences = [_sequence(index) for index in range(442)]
    hashes = [hashlib.sha256(sequence.encode("ascii")).digest() for sequence in sequences]
    labels = [LABEL_ORDER[index % len(LABEL_ORDER)] for index in range(442)]
    partitions = ["train"] * 308 + ["validation"] * 68 + ["test"] * 66
    components = [f"component-{index // 2:03d}" for index in range(442)]
    if blank_test_component:
        components[-1] = ""

    cohort = data / "cohort.parquet"
    pq.write_table(
        pa.table(
            {
                "accession": pa.array(accessions, pa.string()),
                "sequence_sha256": pa.array(hashes, pa.binary(32)),
                "ec_level_2": pa.array(labels, pa.string()),
                "sequence_length": pa.array([50] * 442, pa.uint32()),
                "discovery_component_id_cluster30": pa.array(components, pa.string()),
            }
        ),
        cohort,
    )
    fasta = data / "cohort.fasta"
    fasta.write_text(
        "".join(
            f">sp|{accession}|{accession}_TEST\n{sequence}\n"
            for accession, sequence in zip(accessions, sequences, strict=True)
        ),
        encoding="utf-8",
        newline="\n",
    )
    cohort_content = data / "cohort.json"
    cohort_content.write_text(
        json.dumps(
            {
                "selected_labels": list(LABEL_ORDER),
                "artifacts": {
                    "cohort_manifest": {
                        "file_sha256": sha256_file(cohort),
                        "row_count": 442,
                    },
                    "fasta": {"file_sha256": sha256_file(fasta), "row_count": 442},
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    split = data / "split.parquet"
    pq.write_table(
        pa.table(
            {
                "accession": pa.array(accessions, pa.string()),
                "sequence_sha256": pa.array(hashes, pa.binary(32)),
                "split": pa.array(partitions, pa.string()),
            }
        ),
        split,
    )
    split_content = data / "split.json"
    split_content.write_text(
        json.dumps(
            {
                "artifact": {"file_sha256": sha256_file(split), "row_count": 442},
                "cohort_content_manifest_sha256": sha256_file(cohort_content),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    loaded = load_experiment_config(SOURCE_CONFIG)
    assert isinstance(loaded, FrozenTestExperimentConfig)
    synthetic_cohort = loaded.cohort.model_copy(
        update={
            "manifest": cohort,
            "file_sha256": sha256_file(cohort),
            "semantic_sha256": "1" * 64,
            "content_manifest": cohort_content,
            "content_manifest_sha256": sha256_file(cohort_content),
            "fasta": fasta,
            "fasta_sha256": sha256_file(fasta),
        }
    )
    synthetic_splits = tuple(
        item.model_copy(
            update={
                "manifest": split,
                "file_sha256": sha256_file(split),
                "semantic_sha256": str(index + 2) * 64,
                "content_manifest": split_content,
                "content_manifest_sha256": sha256_file(split_content),
            }
        )
        for index, item in enumerate(loaded.splits)
    )
    return loaded.model_copy(
        update={
            "cohort": synthetic_cohort,
            "splits": synthetic_splits,
            "outputs": loaded.outputs.model_copy(update={"root": root / "runs"}),
            "attestation": root / "attestation.yaml",
        }
    )


def _write_prediction_manifest(
    path: Path,
    bundle: FrozenTestBundle,
) -> dict[str, object]:
    test_records = [record for record in bundle.records if record.partition == "test"]
    mapping: dict[str, object] = {
        "manifest_schema_version": 1,
        "status": "complete",
        "method": "majority",
        "split_name": bundle.split_name,
        "evaluation_partition": "test",
        "row_count": 66,
        "contains_true_labels": False,
        "inventory": [
            {
                "accession": record.accession,
                "sequence_sha256": record.sequence_sha256.hex(),
            }
            for record in test_records
        ],
    }
    path.write_text(json.dumps(mapping, sort_keys=True) + "\n", encoding="utf-8")
    return mapping


def test_frozen_bundle_requires_a_verified_capability_before_any_file_open(tmp_path: Path) -> None:
    config = _write_inputs(tmp_path)
    invalid = cast(VerifiedTestAuthorization, object())

    with pytest.raises(RealTestAccessDenied, match="not authorized"):
        load_frozen_test_bundle(config, "random", invalid)


def test_frozen_bundle_hashes_before_projection_and_excludes_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_inputs(tmp_path)
    import protein_split_audit.evaluation.test_inputs as module

    events: list[tuple[str, object]] = []
    real_hash = module.sha256_file
    real_read = module.pq.read_table

    def observed_hash(path: Path) -> str:
        events.append(("hash", path.name))
        return real_hash(path)

    def observed_read(*args: object, **kwargs: object) -> object:
        events.append(("read", tuple(kwargs.get("columns", ()))))
        return real_read(*args, **kwargs)

    monkeypatch.setattr(module, "sha256_file", observed_hash)
    monkeypatch.setattr(module.pq, "read_table", observed_read)
    bundle = load_frozen_test_bundle(config, "random", _authorization())

    first_read = next(index for index, event in enumerate(events) if event[0] == "read")
    assert all(event[0] == "hash" for event in events[:first_read])
    assert len(bundle.records) == 374
    assert sum(record.partition == "train" for record in bundle.records) == 308
    assert sum(record.partition == "test" for record in bundle.records) == 66
    assert not any(record.partition == "validation" for record in bundle.records)
    assert set(bundle.train_labels) == {
        record.accession for record in bundle.records if record.partition == "train"
    }
    projections = [event[1] for event in events if event[0] == "read"]
    assert (
        "accession",
        "sequence_sha256",
        "sequence_length",
        "discovery_component_id_cluster30",
    ) in projections
    assert ("accession", "ec_level_2") in projections
    assert bundle.label_order == LABEL_ORDER


def test_test_components_must_be_complete_and_preexisting(tmp_path: Path) -> None:
    config = _write_inputs(tmp_path, blank_test_component=True)

    with pytest.raises(ValueError, match="bootstrap component"):
        load_frozen_test_bundle(config, "random", _authorization())


@pytest.mark.parametrize("change", ("missing", "reordered", "true_label"))
def test_test_labels_remain_closed_until_prediction_inventory_is_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    config = _write_inputs(tmp_path)
    bundle = load_frozen_test_bundle(config, "random", _authorization())
    path = tmp_path / "predictions.json"
    mapping = _write_prediction_manifest(path, bundle)
    inventory = mapping["inventory"]
    assert isinstance(inventory, list)
    if change == "missing":
        inventory.pop()
        mapping["row_count"] = 65
    elif change == "reordered":
        inventory.reverse()
    else:
        first = inventory[0]
        assert isinstance(first, dict)
        first["true_label"] = "2.7"
    path.write_text(json.dumps(mapping, sort_keys=True) + "\n", encoding="utf-8")

    import protein_split_audit.evaluation.test_inputs as module

    real_read = module.pq.read_table

    def reject_label_projection(*args: object, **kwargs: object) -> object:
        if kwargs.get("columns") == ["accession", "ec_level_2"]:
            pytest.fail("Test labels opened before prediction inventory validation")
        return real_read(*args, **kwargs)

    monkeypatch.setattr(module.pq, "read_table", reject_label_projection)
    with pytest.raises(ValueError):
        load_test_labels_after_predictions(bundle, path, _authorization())


def test_test_labels_load_only_after_exact_prediction_inventory(tmp_path: Path) -> None:
    config = _write_inputs(tmp_path)
    bundle = load_frozen_test_bundle(config, "random", _authorization())
    path = tmp_path / "predictions.json"
    _write_prediction_manifest(path, bundle)

    labels = load_test_labels_after_predictions(bundle, path, _authorization())

    assert len(labels) == 66
    assert set(labels) == {
        record.accession for record in bundle.records if record.partition == "test"
    }
