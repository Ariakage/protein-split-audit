# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml


@dataclass(frozen=True, slots=True)
class TinyInputs:
    cohort: Path
    cohort_content: Path
    fasta: Path
    split: Path
    split_content: Path


@dataclass(frozen=True, slots=True)
class TinyExperiment:
    config: Path
    output_root: Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tiny_inputs(
    root: Path,
    *,
    test_sequence: str = "XXXX",
    official_headers: bool = False,
) -> TinyInputs:
    root.mkdir(parents=True, exist_ok=True)
    sequences = {"A0": "ACDE", "A1": "AAAA", "A2": test_sequence}
    labels = {"A0": "1.1", "A1": "2.7", "A2": "1.1"}
    assignments = {"A0": "train", "A1": "validation", "A2": "test"}

    cohort = root / "cohort.parquet"
    cohort_table = pa.table(
        {
            "accession": pa.array(list(sequences), type=pa.string()),
            "sequence_sha256": pa.array(
                [hashlib.sha256(value.encode()).digest() for value in sequences.values()],
                type=pa.binary(32),
            ),
            "ec_level_2": pa.array([labels[key] for key in sequences], type=pa.string()),
            "sequence_length": pa.array([len(value) for value in sequences.values()], pa.uint32()),
        }
    )
    pq.write_table(cohort_table, cohort)

    fasta = root / "cohort.fasta"
    fasta.write_text(
        "".join(
            (
                f">sp|{key}|{key}_TEST ec={labels[key]}\n{value}\n"
                if official_headers
                else f">{key}\n{value}\n"
            )
            for key, value in sequences.items()
        ),
        encoding="utf-8",
        newline="\n",
    )
    cohort_content = root / "cohort.json"
    cohort_content.write_text(
        json.dumps(
            {
                "selected_labels": ["1.1", "2.7"],
                "artifacts": {
                    "cohort_manifest": {"file_sha256": _sha(cohort), "row_count": 3},
                    "fasta": {"file_sha256": _sha(fasta), "row_count": 3},
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    split = root / "split.parquet"
    split_table = pa.table(
        {
            "accession": pa.array(list(sequences), type=pa.string()),
            "sequence_sha256": cohort_table["sequence_sha256"],
            "ec_level_2": pa.array([labels[key] for key in sequences], type=pa.string()),
            "split": pa.array([assignments[key] for key in sequences], type=pa.string()),
            "similarity_component_id": pa.array([None, None, None], type=pa.string()),
            "split_name": pa.array(["random"] * 3, type=pa.string()),
            "strategy": pa.array(["sequence_stratified"] * 3, type=pa.string()),
            "seed": pa.array([42] * 3, type=pa.int64()),
        }
    )
    pq.write_table(split_table, split)
    split_content = root / "split.json"
    split_content.write_text(
        json.dumps(
            {
                "artifact": {"file_sha256": _sha(split), "row_count": 3},
                "cohort_content_manifest_sha256": _sha(cohort_content),
                "name": "random",
                "seed": 42,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return TinyInputs(cohort, cohort_content, fasta, split, split_content)


def write_tiny_experiment(root: Path, project_root: Path) -> TinyExperiment:
    """Write a two-class, four-split Validation matrix fixture."""

    data = root / "data"
    data.mkdir(parents=True)
    sequences = {
        "T0": "ACDE",
        "T1": "ACDEF",
        "T2": "AAAAAA",
        "T3": "AAAAAAA",
        "V0": "ACDEFG",
        "V1": "AAAAAAAA",
        "X0": "TEST-CONTENT-MUST-NOT-BE-PARSED",
    }
    labels = {
        "T0": "1.1",
        "T1": "1.1",
        "T2": "2.7",
        "T3": "2.7",
        "V0": "1.1",
        "V1": "2.7",
        "X0": "1.1",
    }
    assignments = {
        key: ("train" if key.startswith("T") else "validation" if key.startswith("V") else "test")
        for key in sequences
    }
    cohort = data / "cohort.parquet"
    hashes = [hashlib.sha256(sequence.encode()).digest() for sequence in sequences.values()]
    pq.write_table(
        pa.table(
            {
                "accession": pa.array(list(sequences), pa.string()),
                "sequence_sha256": pa.array(hashes, pa.binary(32)),
                "ec_level_2": pa.array([labels[key] for key in sequences], pa.string()),
                "sequence_length": pa.array(
                    [len(value) for value in sequences.values()], pa.uint32()
                ),
            }
        ),
        cohort,
    )
    fasta = data / "cohort.fasta"
    fasta.write_text(
        "".join(f">{key}\n{value}\n" for key, value in sequences.items()),
        encoding="utf-8",
        newline="\n",
    )
    cohort_content = data / "cohort.json"
    cohort_content.write_text(
        json.dumps(
            {
                "selected_labels": ["1.1", "2.7"],
                "artifacts": {
                    "cohort_manifest": {"file_sha256": _sha(cohort), "row_count": 7},
                    "fasta": {"file_sha256": _sha(fasta), "row_count": 7},
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    split_entries = []
    for name in ("random", "cluster70", "cluster50", "cluster30"):
        split = data / f"{name}.parquet"
        pq.write_table(
            pa.table(
                {
                    "accession": pa.array(list(sequences), pa.string()),
                    "sequence_sha256": pa.array(hashes, pa.binary(32)),
                    "ec_level_2": pa.array([labels[key] for key in sequences], pa.string()),
                    "split": pa.array([assignments[key] for key in sequences], pa.string()),
                    "similarity_component_id": pa.array([None] * 7, pa.string()),
                    "split_name": pa.array([name] * 7, pa.string()),
                    "strategy": pa.array(["fixture"] * 7, pa.string()),
                    "seed": pa.array([42] * 7, pa.int64()),
                }
            ),
            split,
        )
        content = data / f"{name}.json"
        content.write_text(
            json.dumps(
                {
                    "artifact": {"file_sha256": _sha(split), "row_count": 7},
                    "cohort_content_manifest_sha256": _sha(cohort_content),
                    "name": name,
                    "seed": 42,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        split_entries.append(
            {"name": name, "manifest": str(split), "content_manifest": str(content)}
        )
    output_root = root / "runs"
    mapping = {
        "schema_version": 1,
        "name": "tiny-v030-validation",
        "cohort": {
            "manifest": str(cohort),
            "content_manifest": str(cohort_content),
            "fasta": str(fasta),
        },
        "splits": split_entries,
        "baselines": [
            {"name": "majority", "model_config": str(project_root / "configs/model/majority.yaml")},
            {
                "name": "length_logistic",
                "feature_config": str(project_root / "configs/feature/length.yaml"),
                "model_config": str(project_root / "configs/model/logistic_regression.yaml"),
            },
            {
                "name": "aac_logistic",
                "feature_config": str(project_root / "configs/feature/aac.yaml"),
                "model_config": str(project_root / "configs/model/logistic_regression.yaml"),
            },
            {
                "name": "kmer3_logistic",
                "feature_config": str(project_root / "configs/feature/kmer3.yaml"),
                "model_config": str(project_root / "configs/model/logistic_regression.yaml"),
            },
            {
                "name": "nearest_homolog",
                "model_config": str(project_root / "configs/model/nearest_homolog.yaml"),
            },
        ],
        "evaluation": {
            "split": "validation",
            "label_order_from_cohort": True,
            "zero_division": 0,
            "real_test_access_authorized": False,
        },
        "runtime": {"seed": 42, "feature_threads": 1, "mmseqs_threads": 8},
        "outputs": {"root": str(output_root), "refuse_overwrite": True},
    }
    config = root / "experiment.yaml"
    config.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8", newline="\n")
    return TinyExperiment(config, output_root)
