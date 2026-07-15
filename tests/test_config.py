# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml
from _pytest.monkeypatch import MonkeyPatch
from pydantic import ValidationError

import protein_split_audit.config as config_module
from protein_split_audit.config import (
    CandidateSelectionConfig,
    SourceDownloadConfig,
    load_build_config,
    load_config,
    load_download_config,
)
from protein_split_audit.provenance import serialize_canonical_json

PROJECT_ROOT = Path(__file__).parents[1]
COHORT_SELECTION_RULE_VERSION = "pilot-ec2-5class-min40-c30g10-cap250-seed42-v1"


def test_load_config_resolves_paths_relative_to_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "project.yaml"
    config_path.write_text(
        """\
schema_version: 1
paths:
  data_dir: ../workspace/data
  cache_dir: ../workspace/cache
  results_dir: ../workspace/results
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.schema_version == 1
    assert config.paths.data_dir == (tmp_path / "workspace/data").resolve()
    assert config.paths.cache_dir == (tmp_path / "workspace/cache").resolve()
    assert config.paths.results_dir == (tmp_path / "workspace/results").resolve()


def test_load_config_rejects_unknown_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "project.yaml"
    config_path.write_text("schema_version: 1\nunknown: true\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(config_path)


def test_pilot_download_config_is_valid_and_project_relative() -> None:
    config = load_download_config(PROJECT_ROOT / "configs/dataset/pilot.yaml")

    assert config.run_name == "swissprot-ecoli-k12-enzyme-pilot"
    assert config.source.database == "UniProtKB/Swiss-Prot"
    assert config.source.page_size <= 500
    assert config.source.requested_fields[0] == "accession"
    assert config.output.raw_dir == PROJECT_ROOT / "data/raw"
    assert config.output.manifest_dir == PROJECT_ROOT / "data/manifests"


def test_pilot_build_config_separates_source_and_candidate_rules() -> None:
    config = load_build_config(PROJECT_ROOT / "configs/dataset/pilot.yaml")

    assert config.candidate_selection.allowed_amino_acids == "ACDEFGHIKLMNPQRSTVWY"
    assert config.candidate_selection.min_sequence_length == 50
    assert config.candidate_selection.max_sequence_length == 1000
    assert config.candidate_selection.require_single_ec is True
    assert config.candidate_selection.require_complete_ec is True
    assert config.build_output.processed_dir == PROJECT_ROOT / "data/processed"
    assert config.build_output.parquet_filename == "pilot.parquet"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed_amino_acids", "ACDEFGHIKLMNPQRSTVWYX"),
        ("min_sequence_length", 49),
        ("max_sequence_length", 1001),
        ("require_single_ec", False),
        ("require_complete_ec", False),
    ],
)
def test_candidate_protocol_cannot_be_broadened(field: str, value: object) -> None:
    candidate = {
        "allowed_amino_acids": "ACDEFGHIKLMNPQRSTVWY",
        "min_sequence_length": 50,
        "max_sequence_length": 1000,
        "require_single_ec": True,
        "require_complete_ec": True,
    }
    candidate[field] = value

    with pytest.raises(ValidationError):
        CandidateSelectionConfig.model_validate(candidate)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://rest.uniprot.org/uniprotkb/search",
        "https://token:secret@rest.uniprot.org/uniprotkb/search",
        "https://example.org/uniprotkb/search",
    ],
)
def test_download_source_rejects_unapproved_endpoint(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="approved UniProtKB HTTPS endpoint"):
        SourceDownloadConfig.model_validate(
            {
                "database": "UniProtKB/Swiss-Prot",
                "endpoint": endpoint,
                "query": "reviewed:true",
                "fields": [{"name": "accession", "response_header": "Entry", "required": True}],
                "page_size": 1,
                "timeout_seconds": 1.0,
            }
        )


def _write_yaml(tmp_path: Path, name: str, mapping: dict[str, Any]) -> Path:
    config_dir = tmp_path / "nested" / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / name
    config_path.write_text(
        yaml.safe_dump(mapping, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return config_path


def _load_v020(loader_name: str, config_path: Path) -> Any:
    loader = getattr(config_module, loader_name, None)
    assert callable(loader), f"{loader_name} must be implemented"
    return loader(config_path)


def _runtime() -> dict[str, Any]:
    return {
        "executable": "mmseqs",
        "cache_root": "../cache/mmseqs",
        "timeout_seconds": 3600,
        "threads": 8,
    }


def _cluster(min_sequence_identity: float) -> dict[str, Any]:
    return {
        "sensitivity": 7.5,
        "evalue": 0.001,
        "sequence_identity_mode": 0,
        "min_sequence_identity": min_sequence_identity,
        "minimum_coverage": 0.80,
        "coverage_mode": 0,
        "alignment_mode": 3,
        "cluster_mode": 0,
        "cluster_reassign": True,
    }


def _self_search() -> dict[str, Any]:
    return {
        "sensitivity": 7.5,
        "evalue": 0.001,
        "search_type": 1,
        "sequence_identity_mode": 0,
        "min_sequence_identity": 0.30,
        "minimum_coverage": 0.80,
        "coverage_mode": 0,
        "alignment_mode": 3,
        "format_mode": 4,
    }


def _audit_search() -> dict[str, Any]:
    search = _self_search()
    search["min_sequence_identity"] = 0.0
    return search


def _cohort_mapping(
    *,
    min_sequences_per_class: int = 40,
    number_of_classes: int = 5,
    run_mode: str = "development",
) -> dict[str, Any]:
    cohort_version = "pilot-v1" if run_mode == "freeze" else "pilot-v1-candidate"
    input_mapping = {
        "candidate_dataset": "../inputs/pilot.parquet",
        "candidate_fasta": "../inputs/pilot.fasta",
        "raw_download": "../inputs/pilot.tsv.gz",
        "build_manifest": "../inputs/pilot.build.json",
        "download_manifest": "../inputs/pilot.download.json",
        "discovery_components": "../inputs/components.parquet",
        "discovery_content_manifest": "../inputs/components.json",
    }
    if run_mode == "freeze":
        input_mapping.update(
            {
                "difference_report": "../inputs/regeneration-difference.json",
                "review_attestation": "../inputs/freeze-review.json",
            }
        )
    return {
        "schema_version": 1,
        "cohort_version": cohort_version,
        "run_mode": run_mode,
        "input": input_mapping,
        "selection": {
            "selection_rule_version": COHORT_SELECTION_RULE_VERSION,
            "label_field": "ec_level_2",
            "min_sequences_per_class": min_sequences_per_class,
            "min_groups_per_class_at_cluster30": 10,
            "max_sequences_per_class": 250,
            "number_of_classes": number_of_classes,
            "seed": 42,
            "class_ranking": "capped_count_desc_group_count_desc_label_asc_v1",
            "member_ranking": "component_round_robin_sha256_v1",
        },
        "feasibility": {
            "ratios": {"train": 0.70, "validation": 0.15, "test": 0.15},
            "ratio_tolerance": 0.05,
            "allocator": {
                "version": "greedy_component_loss_v1",
                "size_weight": 1.0,
                "class_balance_weight": 3.0,
                "group_count_weight": 0.5,
                "missing_class_weight": 10.0,
            },
        },
        "output": {
            "cohort_manifest": f"../outputs/{cohort_version}.parquet",
            "content_manifest": f"../outputs/{cohort_version}.json",
            "fasta": f"../outputs/{cohort_version}.fasta",
            "run_dir": f"../runs/cohort-{cohort_version}",
            "overwrite": False,
        },
    }


def _candidate_discovery_mapping() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "candidate_discovery",
        "name": "candidate-pool-cluster30",
        "run_mode": "development",
        "runtime": _runtime(),
        "self_search": _self_search(),
        "input": {
            "candidate_dataset": "../inputs/pilot.parquet",
            "build_manifest": "../inputs/pilot.build.json",
            "fasta": "../inputs/pilot.fasta",
        },
        "output": {
            "component_manifest": "../outputs/candidate-components.parquet",
            "content_manifest": "../outputs/candidate-components.json",
            "pair_table": "../outputs/candidate-pairs.parquet",
            "run_dir": "../runs/candidate-discovery",
            "overwrite": False,
        },
    }


def _cohort_cluster_base_mapping() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "cohort_cluster_base",
        "name": "cluster30",
        "run_mode": "development",
        "runtime": _runtime(),
        "cluster": _cluster(0.30),
        "self_search": _self_search(),
        "input": {
            "cohort_manifest": "../inputs/pilot-v1.parquet",
            "cohort_content_manifest": "../inputs/pilot-v1.json",
            "fasta": "../inputs/pilot-v1.fasta",
        },
        "output": {
            "cluster_manifest": "../outputs/cluster30.parquet",
            "content_manifest": "../outputs/cluster30.json",
            "pair_table": "../outputs/pairs30.parquet",
            "run_dir": "../runs/cluster30",
            "overwrite": False,
        },
    }


def _cohort_cluster_derived_mapping(
    *, name: str = "cluster50", min_sequence_identity: float = 0.50
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "cohort_cluster_derived",
        "name": name,
        "run_mode": "development",
        "runtime": _runtime(),
        "cluster": _cluster(min_sequence_identity),
        "input": {
            "cohort_manifest": "../inputs/pilot-v1.parquet",
            "cohort_content_manifest": "../inputs/pilot-v1.json",
            "fasta": "../inputs/pilot-v1.fasta",
            "base_pair_table": "../inputs/pairs30.parquet",
            "base_pair_content_manifest": "../inputs/pairs30.json",
            "base_pair_sha256": "a" * 64,
        },
        "output": {
            "cluster_manifest": f"../outputs/{name}.parquet",
            "content_manifest": f"../outputs/{name}.json",
            "run_dir": f"../runs/{name}",
            "overwrite": False,
        },
    }


def _audit_mapping(
    *,
    name: str = "cluster30",
    strategy: str = "similarity_component",
    violation_identity_threshold: float | None = 0.30,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "audit",
        "name": name,
        "strategy": strategy,
        "run_mode": "development",
        "violation_identity_threshold": violation_identity_threshold,
        "runtime": _runtime(),
        "search": _audit_search(),
        "input": {
            "split_manifest": "../inputs/split.parquet",
            "split_content_manifest": "../inputs/split.json",
            "cohort_manifest": "../inputs/pilot-v1.parquet",
            "cohort_content_manifest": "../inputs/pilot-v1.json",
            "cohort_fasta": "../inputs/pilot-v1.fasta",
        },
        "output": {
            "train_fasta": f"../outputs/{name}/train.fasta",
            "test_fasta": f"../outputs/{name}/test.fasta",
            "audit_manifest": f"../outputs/{name}/audit.parquet",
            "content_manifest": f"../outputs/{name}/audit.json",
            "summary": f"../runs/{name}/summary.json",
            "run_dir": f"../runs/{name}",
            "overwrite": False,
        },
    }


def _split_mapping(*, component: bool) -> dict[str, Any]:
    name = "cluster30" if component else "random"
    input_mapping: dict[str, Any] = {
        "cohort_manifest": "../inputs/pilot-v1.parquet",
        "cohort_content_manifest": "../inputs/pilot-v1.json",
    }
    mapping: dict[str, Any] = {
        "schema_version": 1,
        "name": name,
        "strategy": "similarity_component" if component else "sequence_stratified",
        "run_mode": "development",
        "input": input_mapping,
        "ratios": {"train": 0.70, "validation": 0.15, "test": 0.15},
        "seed": 42,
        "stratify_by": "ec_level_2",
        "ratio_tolerance": 0.05,
        "output": {
            "manifest": f"../outputs/{name}.parquet",
            "content_manifest": f"../outputs/{name}.json",
            "run_dir": f"../runs/{name}",
            "overwrite": False,
        },
    }
    if component:
        input_mapping.update(
            {
                "component_manifest": "../inputs/components.parquet",
                "component_content_manifest": "../inputs/components.json",
            }
        )
        mapping["allocator"] = {
            "version": "greedy_component_loss_v1",
            "size_weight": 1.0,
            "class_balance_weight": 3.0,
            "group_count_weight": 0.5,
            "missing_class_weight": 10.0,
        }
    return mapping


def test_load_cohort_config_resolves_paths_and_freezes_fixed_protocol(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, "cohort.yaml", _cohort_mapping())

    config = _load_v020("load_cohort_config", config_path)

    expected_base = config_path.parent.parent
    assert type(config).__name__ == "DevelopmentCohortConfig"
    assert config.cohort_version == "pilot-v1-candidate"
    assert config.input.candidate_dataset == (expected_base / "inputs/pilot.parquet").resolve()
    assert config.input.candidate_fasta == (expected_base / "inputs/pilot.fasta").resolve()
    assert config.input.raw_download == (expected_base / "inputs/pilot.tsv.gz").resolve()
    assert (
        config.input.download_manifest == (expected_base / "inputs/pilot.download.json").resolve()
    )
    assert config.output.run_dir == (expected_base / "runs/cohort-pilot-v1-candidate").resolve()
    assert config.selection.selection_rule_version == COHORT_SELECTION_RULE_VERSION
    assert config.selection.min_sequences_per_class == 40
    assert config.selection.min_groups_per_class_at_cluster30 == 10
    assert config.selection.max_sequences_per_class == 250
    assert config.selection.number_of_classes == 5
    assert config.selection.seed == 42
    assert config.feasibility.ratios.model_dump() == {
        "train": 0.70,
        "validation": 0.15,
        "test": 0.15,
    }
    assert config.feasibility.ratio_tolerance == 0.05
    assert config.feasibility.allocator.model_dump() == {
        "version": "greedy_component_loss_v1",
        "size_weight": 1.0,
        "class_balance_weight": 3.0,
        "group_count_weight": 0.5,
        "missing_class_weight": 10.0,
    }
    with pytest.raises(ValidationError, match="frozen"):
        config.run_mode = "freeze"


def test_clean_regeneration_config_preserves_scientific_protocol_with_distinct_outputs() -> None:
    loader = _load_v020
    historical_path = PROJECT_ROOT / "configs/dataset/pilot.yaml"
    regeneration_path = PROJECT_ROOT / "configs/dataset/pilot-clean-regeneration.yaml"

    historical = loader("load_build_config", historical_path)
    regenerated = loader("load_build_config", regeneration_path)

    assert regenerated.source == historical.source
    assert regenerated.retry == historical.retry
    assert regenerated.candidate_selection == historical.candidate_selection
    assert regenerated.output.raw_dir != historical.output.raw_dir
    assert regenerated.output.manifest_dir != historical.output.manifest_dir
    assert regenerated.build_output.processed_dir != historical.build_output.processed_dir
    assert regenerated.build_output.manifest_dir != historical.build_output.manifest_dir
    assert (
        regenerated.output.manifest_dir
        == (PROJECT_ROOT / "data/manifests/v0.2.0/regeneration").resolve()
    )


@pytest.mark.parametrize(
    ("min_sequences_per_class", "number_of_classes"),
    [(50, 4), (40, 4), (50, 5), (60, 5)],
)
def test_cohort_config_rejects_unapproved_threshold_class_pairs(
    tmp_path: Path,
    min_sequences_per_class: int,
    number_of_classes: int,
) -> None:
    mapping = _cohort_mapping(
        min_sequences_per_class=min_sequences_per_class,
        number_of_classes=number_of_classes,
    )
    config_path = _write_yaml(tmp_path, "cohort-unapproved.yaml", mapping)

    with pytest.raises(ValidationError):
        _load_v020("load_cohort_config", config_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selection_rule_version", "pilot-four-class-v1"),
        ("min_groups_per_class_at_cluster30", 9),
        ("max_sequences_per_class", 251),
        ("seed", 43),
    ],
)
def test_cohort_config_rejects_changes_to_approved_selection_rule(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    mapping = _cohort_mapping()
    mapping["selection"][field] = value
    config_path = _write_yaml(tmp_path, "cohort-rule-change.yaml", mapping)

    with pytest.raises(ValidationError, match=field):
        _load_v020("load_cohort_config", config_path)


def test_cohort_config_requires_explicit_candidate_fasta(tmp_path: Path) -> None:
    mapping = _cohort_mapping()
    del mapping["input"]["candidate_fasta"]
    config_path = _write_yaml(tmp_path, "cohort-missing-fasta.yaml", mapping)

    with pytest.raises(ValidationError, match="candidate_fasta"):
        _load_v020("load_cohort_config", config_path)


def test_freeze_cohort_config_requires_review_inputs(tmp_path: Path) -> None:
    mapping = _cohort_mapping(run_mode="freeze")
    del mapping["input"]["review_attestation"]
    config_path = _write_yaml(tmp_path, "cohort-freeze.yaml", mapping)

    with pytest.raises(ValidationError, match="review_attestation"):
        _load_v020("load_cohort_config", config_path)


def test_development_cohort_config_rejects_freeze_only_inputs(tmp_path: Path) -> None:
    mapping = _cohort_mapping()
    mapping["input"]["difference_report"] = "../inputs/difference.json"
    mapping["input"]["review_attestation"] = "../inputs/review.json"
    config_path = _write_yaml(tmp_path, "cohort-development.yaml", mapping)

    with pytest.raises(ValidationError):
        _load_v020("load_cohort_config", config_path)


def test_freeze_cohort_config_discriminates_and_resolves_review_inputs(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, "cohort-freeze.yaml", _cohort_mapping(run_mode="freeze"))

    config = _load_v020("load_cohort_config", config_path)

    expected_base = config_path.parent.parent
    assert type(config).__name__ == "FreezeCohortConfig"
    assert config.cohort_version == "pilot-v1"
    assert (
        config.input.difference_report
        == (expected_base / "inputs/regeneration-difference.json").resolve()
    )
    assert (
        config.input.review_attestation == (expected_base / "inputs/freeze-review.json").resolve()
    )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("ratios", "train", 0.69),
        (None, "ratio_tolerance", 0.04),
        ("allocator", "class_balance_weight", 2.0),
    ],
)
def test_cohort_config_rejects_changes_to_feasibility_protocol(
    tmp_path: Path,
    section: str | None,
    field: str,
    value: object,
) -> None:
    mapping = _cohort_mapping()
    target = mapping["feasibility"] if section is None else mapping["feasibility"][section]
    target[field] = value
    if section == "ratios" and field == "train":
        target["validation"] = 0.16
    config_path = _write_yaml(tmp_path, "cohort-feasibility.yaml", mapping)

    with pytest.raises(ValidationError, match=field):
        _load_v020("load_cohort_config", config_path)


def test_cohort_config_document_preserves_exact_source_and_logical_paths(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    mapping = _cohort_mapping()
    config_path = tmp_path / "nested/configs/cohort.yaml"
    config_path.parent.mkdir(parents=True)
    source_bytes = (
        ("# exact cohort source: café\n" + yaml.safe_dump(mapping, sort_keys=False))
        .replace("\n", "\r\n")
        .encode()
    )
    config_path.write_bytes(source_bytes)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    loader = getattr(config_module, "load_cohort_config_document", None)

    assert callable(loader), "load_cohort_config_document must be public"
    document = loader(config_path)

    assert document.source_path == config_path.resolve()
    assert document.source_bytes == source_bytes
    assert document.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    logical_input = document.logical_mapping["input"]
    logical_output = document.logical_mapping["output"]
    assert isinstance(logical_input, Mapping)
    assert isinstance(logical_output, Mapping)
    assert logical_input["candidate_dataset"] == "../inputs/pilot.parquet"
    assert logical_input["candidate_fasta"] == "../inputs/pilot.fasta"
    assert logical_output["cohort_manifest"] == "../outputs/pilot-v1-candidate.parquet"
    assert (
        document.config.input.candidate_fasta
        == (config_path.parent / "../inputs/pilot.fasta").resolve()
    )
    assert str(tmp_path) not in repr(document.logical_mapping)
    assert (
        document.effective_sha256
        == hashlib.sha256(serialize_canonical_json(document.logical_mapping)).hexdigest()
    )
    with pytest.raises(TypeError):
        logical_input["candidate_fasta"] = "changed.fasta"  # type: ignore[index]


def test_checked_in_cohort_config_is_provisional_and_protocol_locked() -> None:
    config_path = PROJECT_ROOT / "configs/cohort/pilot.yaml"

    assert config_path.is_file(), "provisional cohort config must be checked in"
    document = _load_v020("load_cohort_config_document", config_path)
    config = document.config

    assert type(config).__name__ == "DevelopmentCohortConfig"
    assert config.cohort_version == "pilot-v1-candidate"
    assert config.run_mode == "development"
    assert config.input.candidate_dataset == PROJECT_ROOT / "data/processed/pilot.parquet"
    assert config.input.candidate_fasta == PROJECT_ROOT / "data/processed/pilot.fasta"
    assert config.input.build_manifest == PROJECT_ROOT / "data/manifests/pilot.build.json"
    assert config.input.download_manifest == (
        PROJECT_ROOT / "data/manifests/swissprot-ecoli-k12-enzyme-pilot.download.json"
    )
    assert config.input.discovery_components == (
        PROJECT_ROOT / "data/manifests/similarity/candidate-pool-cluster30.parquet"
    )
    assert config.input.discovery_content_manifest == (
        PROJECT_ROOT / "data/manifests/similarity/candidate-pool-cluster30.json"
    )
    assert config.selection.model_dump() == {
        "selection_rule_version": COHORT_SELECTION_RULE_VERSION,
        "label_field": "ec_level_2",
        "min_sequences_per_class": 40,
        "min_groups_per_class_at_cluster30": 10,
        "max_sequences_per_class": 250,
        "number_of_classes": 5,
        "seed": 42,
        "class_ranking": "capped_count_desc_group_count_desc_label_asc_v1",
        "member_ranking": "component_round_robin_sha256_v1",
    }
    assert config.output.cohort_manifest == (
        PROJECT_ROOT / "data/manifests/cohorts/pilot-v1-candidate.parquet"
    )
    assert config.output.content_manifest == (
        PROJECT_ROOT / "data/manifests/cohorts/pilot-v1-candidate.json"
    )
    assert config.output.fasta == (PROJECT_ROOT / "data/processed/cohorts/pilot-v1-candidate.fasta")
    assert config.output.run_dir == PROJECT_ROOT / "results/runs/cohort-pilot-v1-candidate"
    assert "difference_report" not in document.logical_mapping["input"]
    assert "review_attestation" not in document.logical_mapping["input"]


@pytest.mark.parametrize(
    ("mapping", "expected_type"),
    [
        (_candidate_discovery_mapping(), "CandidateDiscoveryConfig"),
        (_cohort_cluster_base_mapping(), "CohortClusterBaseConfig"),
        (_cohort_cluster_derived_mapping(), "CohortClusterDerivedConfig"),
        (
            _cohort_cluster_derived_mapping(name="cluster70", min_sequence_identity=0.70),
            "CohortClusterDerivedConfig",
        ),
        (_audit_mapping(), "AuditConfig"),
        (
            _audit_mapping(
                name="random",
                strategy="random_control",
                violation_identity_threshold=None,
            ),
            "AuditConfig",
        ),
    ],
)
def test_load_similarity_config_discriminates_operations_and_resolves_paths(
    tmp_path: Path, mapping: dict[str, Any], expected_type: str
) -> None:
    config_path = _write_yaml(tmp_path, "similarity.yaml", mapping)

    config = _load_v020("load_similarity_config", config_path)

    expected_base = config_path.parent.parent
    assert type(config).__name__ == expected_type
    assert config.runtime.cache_root == (expected_base / "cache/mmseqs").resolve()
    assert all(
        path.is_absolute() for path in config.input.model_dump().values() if isinstance(path, Path)
    )
    assert all(
        path.is_absolute() for path in config.output.model_dump().values() if isinstance(path, Path)
    )
    assert config.runtime.timeout_seconds == 3600


def test_candidate_discovery_similarity_config_is_fixed_and_project_relative() -> None:
    config_path = PROJECT_ROOT / "configs/similarity/candidate-pool-cluster30.yaml"

    assert config_path.is_file(), "candidate discovery config must be checked in"
    document = _load_v020("load_similarity_config_document", config_path)
    config = document.config

    assert type(config).__name__ == "CandidateDiscoveryConfig"
    assert config.operation == "candidate_discovery"
    assert config.name == "candidate-pool-cluster30"
    assert config.run_mode == "development"
    assert config.runtime.executable == "mmseqs"
    assert config.runtime.cache_root == PROJECT_ROOT / "cache/mmseqs"
    assert config.runtime.timeout_seconds == 3600
    assert config.runtime.threads == 8
    assert config.self_search.model_dump() == {
        "sensitivity": 7.5,
        "evalue": 0.001,
        "search_type": 1,
        "sequence_identity_mode": 0,
        "min_sequence_identity": 0.30,
        "minimum_coverage": 0.80,
        "coverage_mode": 0,
        "alignment_mode": 3,
        "format_mode": 4,
    }
    assert config.input.candidate_dataset == PROJECT_ROOT / "data/processed/pilot.parquet"
    assert config.input.build_manifest == PROJECT_ROOT / "data/manifests/pilot.build.json"
    assert config.input.fasta == PROJECT_ROOT / "data/processed/pilot.fasta"
    assert config.output.component_manifest == (
        PROJECT_ROOT / "data/manifests/similarity/candidate-pool-cluster30.parquet"
    )
    assert config.output.content_manifest == (
        PROJECT_ROOT / "data/manifests/similarity/candidate-pool-cluster30.json"
    )
    assert config.output.pair_table == (
        PROJECT_ROOT / "data/processed/similarity/candidate-pool-pairs30.parquet"
    )
    assert config.output.run_dir == (
        PROJECT_ROOT / "results/runs/similarity-candidate-pool-cluster30"
    )
    assert config.output.overwrite is False
    assert "cluster" not in document.logical_mapping
    assert "cohort_manifest" not in document.logical_mapping["input"]


def test_clean_regeneration_discovery_config_is_tracked_and_release_eligible() -> None:
    config_path = (
        PROJECT_ROOT / "configs/similarity/candidate-pool-cluster30-clean-regeneration.yaml"
    )

    assert config_path.is_file(), "clean discovery config must be checked in"
    document = _load_v020("load_similarity_config_document", config_path)
    config = document.config

    assert type(config).__name__ == "CandidateDiscoveryConfig"
    assert config.operation == "candidate_discovery"
    assert config.name == "candidate-pool-cluster30"
    assert config.run_mode == "freeze"
    assert config.runtime.executable == "mmseqs"
    assert config.self_search.min_sequence_identity == 0.30
    assert config.self_search.minimum_coverage == 0.80
    assert config.input.candidate_dataset == (
        PROJECT_ROOT / "data/processed/v0.2.0-clean-regeneration/pilot.parquet"
    )
    assert config.input.build_manifest == (
        PROJECT_ROOT / "data/manifests/v0.2.0/regeneration/pilot.build.json"
    )
    assert config.input.fasta == (
        PROJECT_ROOT / "data/processed/v0.2.0-clean-regeneration/pilot.fasta"
    )
    assert config.output.component_manifest == (
        PROJECT_ROOT / "data/manifests/v0.2.0/regeneration/candidate-pool-cluster30.parquet"
    )
    assert config.output.content_manifest == (
        PROJECT_ROOT / "data/manifests/v0.2.0/regeneration/candidate-pool-cluster30.json"
    )
    assert config.output.pair_table == (
        PROJECT_ROOT
        / "data/processed/v0.2.0-clean-regeneration/similarity/candidate-pool-pairs30.parquet"
    )
    assert config.output.run_dir == (
        PROJECT_ROOT / "results/runs/v0.2.0-clean-regeneration-similarity-cluster30"
    )
    assert config.output.overwrite is False


def test_pilot_freeze_config_binds_clean_lineage_and_external_review() -> None:
    config_path = PROJECT_ROOT / "configs/cohort/pilot-freeze.yaml"

    assert config_path.is_file(), "pilot freeze config must be checked in before generation"
    document = _load_v020("load_cohort_config_document", config_path)
    config = document.config

    assert type(config).__name__ == "FreezeCohortConfig"
    assert config.cohort_version == "pilot-v1"
    assert config.run_mode == "freeze"
    assert config.input.candidate_dataset == (
        PROJECT_ROOT / "data/processed/v0.2.0-clean-regeneration/pilot.parquet"
    )
    assert config.input.discovery_content_manifest == (
        PROJECT_ROOT / "data/manifests/v0.2.0/regeneration/candidate-pool-cluster30.json"
    )
    assert config.input.difference_report == (
        PROJECT_ROOT
        / "results/runs/v0.2.0-clean-regeneration-review/formal-generation-a"
        / "candidate-regeneration-difference.json"
    )
    assert config.input.review_attestation == (
        PROJECT_ROOT
        / "results/runs/v0.2.0-clean-regeneration-review/formal-generation-a"
        / "pilot-v1-freeze-review.json"
    )
    assert config.output.cohort_manifest == (
        PROJECT_ROOT / "data/manifests/cohorts/pilot-v1.parquet"
    )
    assert config.output.content_manifest == (PROJECT_ROOT / "data/manifests/cohorts/pilot-v1.json")
    assert config.output.fasta == PROJECT_ROOT / "data/processed/cohorts/pilot-v1.fasta"
    assert config.output.overwrite is False


def test_similarity_config_document_preserves_exact_source_and_separates_logical_paths(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    mapping = _candidate_discovery_mapping()
    mapping["runtime"]["executable"] = "../bin/mmseqs"
    config_path = tmp_path / "nested/configs/similarity.yaml"
    config_path.parent.mkdir(parents=True)
    source_bytes = (
        ("# exact source bytes: café\n" + yaml.safe_dump(mapping, sort_keys=False))
        .replace("\n", "\r\n")
        .encode()
    )
    config_path.write_bytes(source_bytes)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    loader = getattr(config_module, "load_similarity_config_document", None)

    assert callable(loader), "load_similarity_config_document must be public"
    document = loader(config_path)

    assert document.source_path == config_path.resolve()
    assert document.source_bytes == source_bytes
    assert document.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    logical_runtime = document.logical_mapping["runtime"]
    logical_input = document.logical_mapping["input"]
    assert isinstance(logical_runtime, Mapping)
    assert isinstance(logical_input, Mapping)
    assert logical_runtime["executable"] == "../bin/mmseqs"
    assert logical_input["candidate_dataset"] == "../inputs/pilot.parquet"
    assert document.config.runtime.executable == str(
        (config_path.parent / "../bin/mmseqs").resolve()
    )
    assert (
        document.config.input.candidate_dataset
        == (config_path.parent / "../inputs/pilot.parquet").resolve()
    )
    assert str(tmp_path) not in repr(document.logical_mapping)


def test_similarity_config_document_hashes_compact_canonical_logical_mapping(
    tmp_path: Path,
) -> None:
    config_path = _write_yaml(tmp_path, "similarity.yaml", _candidate_discovery_mapping())

    document = _load_v020("load_similarity_config_document", config_path)

    canonical_bytes = serialize_canonical_json(document.logical_mapping)
    assert document.effective_sha256 == hashlib.sha256(canonical_bytes).hexdigest()
    assert canonical_bytes.endswith(b"\n")
    assert b"\n" not in canonical_bytes[:-1]
    assert str(tmp_path).encode() not in canonical_bytes


def test_similarity_config_document_separates_source_and_effective_hash_identity(
    tmp_path: Path,
) -> None:
    mapping = _candidate_discovery_mapping()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    first_path = config_dir / "first.yaml"
    second_path = config_dir / "second.yaml"
    first_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8", newline="\n")
    reordered_mapping = {key: mapping[key] for key in reversed(mapping)}
    second_path.write_text(
        "# semantically identical, differently ordered source\n"
        + yaml.safe_dump(reordered_mapping, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )

    first = _load_v020("load_similarity_config_document", first_path)
    second = _load_v020("load_similarity_config_document", second_path)

    assert first.source_sha256 != second.source_sha256
    assert first.logical_mapping == second.logical_mapping
    assert first.effective_sha256 == second.effective_sha256


def test_similarity_config_document_uses_validated_effective_defaults_and_logical_paths(
    tmp_path: Path,
) -> None:
    mapping = _candidate_discovery_mapping()
    absolute_cache = (tmp_path / "local/cache/mmseqs").resolve()
    absolute_executable = (tmp_path / "local/bin/mmseqs").resolve()
    absolute_candidate = (tmp_path / "local/data/pilot.parquet").resolve()
    mapping["runtime"]["cache_root"] = str(absolute_cache)
    mapping["runtime"]["executable"] = str(absolute_executable)
    mapping["input"]["candidate_dataset"] = str(absolute_candidate)
    mapping["output"].pop("overwrite")
    config_path = _write_yaml(tmp_path, "similarity.yaml", mapping)

    document = _load_v020("load_similarity_config_document", config_path)

    logical_runtime = document.logical_mapping["runtime"]
    logical_input = document.logical_mapping["input"]
    logical_output = document.logical_mapping["output"]
    assert isinstance(logical_runtime, Mapping)
    assert isinstance(logical_input, Mapping)
    assert isinstance(logical_output, Mapping)
    expected_cache = Path(os.path.relpath(absolute_cache, config_path.parent)).as_posix()
    expected_executable = Path(os.path.relpath(absolute_executable, config_path.parent)).as_posix()
    expected_candidate = Path(os.path.relpath(absolute_candidate, config_path.parent)).as_posix()
    assert logical_runtime["cache_root"] == expected_cache
    assert logical_runtime["executable"] == expected_executable
    assert logical_input["candidate_dataset"] == expected_candidate
    assert logical_output["overwrite"] is False
    assert str(tmp_path) not in repr(document.logical_mapping)


def test_legacy_similarity_loader_reads_and_validates_through_one_document_load(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = _write_yaml(tmp_path, "similarity.yaml", _candidate_discovery_mapping())
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []

    def recording_read_bytes(path: Path) -> bytes:
        reads.append(path.resolve())
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read_bytes)

    config = _load_v020("load_similarity_config", config_path)

    assert config.operation == "candidate_discovery"
    assert reads == [config_path.resolve()]


def test_similarity_config_document_is_deeply_frozen(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, "similarity.yaml", _candidate_discovery_mapping())
    document = _load_v020("load_similarity_config_document", config_path)
    logical_mapping: Any = document.logical_mapping
    logical_runtime: Any = document.logical_mapping["runtime"]

    with pytest.raises(TypeError):
        logical_mapping["name"] = "changed"
    with pytest.raises(TypeError):
        logical_runtime["executable"] = "changed"
    with pytest.raises(FrozenInstanceError):
        document.source_bytes = b"changed"

    caller_mapping: dict[str, Any] = {"runtime": {"executable": "mmseqs"}}
    constructed = type(document)(
        source_path=document.source_path,
        source_bytes=document.source_bytes,
        source_sha256=document.source_sha256,
        logical_mapping=caller_mapping,
        effective_sha256=document.effective_sha256,
        config=document.config,
    )
    caller_mapping["runtime"]["executable"] = "changed"
    constructed_runtime: Any = constructed.logical_mapping["runtime"]
    assert constructed_runtime["executable"] == "mmseqs"
    with pytest.raises(TypeError):
        constructed_runtime["executable"] = "changed"


@pytest.mark.parametrize("configured_executable", ["../bin/mmseqs", "./bin/mmseqs", "."])
def test_load_similarity_config_resolves_explicit_runtime_executable_from_config_location(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    configured_executable: str,
) -> None:
    mapping = _candidate_discovery_mapping()
    mapping["runtime"]["executable"] = configured_executable
    config_path = _write_yaml(tmp_path, "similarity.yaml", mapping)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    config = _load_v020("load_similarity_config", config_path)

    assert config.runtime.executable == str((config_path.parent / configured_executable).resolve())


def test_load_similarity_config_preserves_bare_runtime_executable_name(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = _write_yaml(tmp_path, "similarity.yaml", _candidate_discovery_mapping())
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    config = _load_v020("load_similarity_config", config_path)

    assert config.runtime.executable == "mmseqs"


@pytest.mark.parametrize("component", [False, True])
def test_load_split_config_discriminates_strategy_and_resolves_paths(
    tmp_path: Path, component: bool
) -> None:
    config_path = _write_yaml(tmp_path, "split.yaml", _split_mapping(component=component))

    config = _load_v020("load_split_config", config_path)

    expected_base = config_path.parent.parent
    expected_type = (
        "SimilarityComponentSplitConfig" if component else "SequenceStratifiedSplitConfig"
    )
    assert type(config).__name__ == expected_type
    assert config.input.cohort_manifest == (expected_base / "inputs/pilot-v1.parquet").resolve()
    assert config.output.manifest == (expected_base / f"outputs/{config.name}.parquet").resolve()
    assert tuple(config.ratios.model_dump().values()) == (0.70, 0.15, 0.15)
    assert config.seed == 42


@pytest.mark.parametrize(
    ("loader_name", "mapping"),
    [
        ("load_cohort_config", _cohort_mapping()),
        ("load_similarity_config", _candidate_discovery_mapping()),
        ("load_split_config", _split_mapping(component=False)),
    ],
)
def test_v020_configs_reject_unknown_keys(
    tmp_path: Path, loader_name: str, mapping: dict[str, Any]
) -> None:
    mapping["unexpected"] = True
    config_path = _write_yaml(tmp_path, "unknown.yaml", mapping)

    with pytest.raises(ValidationError, match="unexpected"):
        _load_v020(loader_name, config_path)


@pytest.mark.parametrize(
    "mapping",
    [
        {**_candidate_discovery_mapping(), "cluster": _cluster(0.30)},
        {**_cohort_cluster_derived_mapping(), "self_search": _self_search()},
        {**_audit_mapping(), "cluster": _cluster(0.30)},
    ],
)
def test_similarity_operations_reject_inapplicable_parameter_blocks(
    tmp_path: Path, mapping: dict[str, Any]
) -> None:
    config_path = _write_yaml(tmp_path, "inapplicable.yaml", mapping)

    with pytest.raises(ValidationError):
        _load_v020("load_similarity_config", config_path)


def test_cluster_parameters_reject_search_only_fields(tmp_path: Path) -> None:
    mapping = _cohort_cluster_base_mapping()
    mapping["cluster"]["search_type"] = 1
    config_path = _write_yaml(tmp_path, "wrong-parameter.yaml", mapping)

    with pytest.raises(ValidationError, match="search_type"):
        _load_v020("load_similarity_config", config_path)


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("inf")])
def test_similarity_runtime_requires_finite_positive_timeout(
    tmp_path: Path, timeout_seconds: float
) -> None:
    mapping = _candidate_discovery_mapping()
    mapping["runtime"]["timeout_seconds"] = timeout_seconds
    config_path = _write_yaml(tmp_path, "timeout.yaml", mapping)

    with pytest.raises(ValidationError, match="timeout_seconds"):
        _load_v020("load_similarity_config", config_path)


@pytest.mark.parametrize("invalid_path", [None, False, 123, [], ""])
def test_v020_paths_reject_non_string_or_blank_values(tmp_path: Path, invalid_path: object) -> None:
    mapping = _candidate_discovery_mapping()
    mapping["input"]["fasta"] = invalid_path
    config_path = _write_yaml(tmp_path, "invalid-path.yaml", mapping)

    with pytest.raises(ValueError, match="path"):
        _load_v020("load_similarity_config", config_path)


@pytest.mark.parametrize(
    ("mapping", "section", "field", "value"),
    [
        (_cohort_mapping(), "selection", "min_sequences_per_class", 41),
        (_candidate_discovery_mapping(), "self_search", "min_sequence_identity", 0.31),
        (_cohort_cluster_base_mapping(), "cluster", "minimum_coverage", 0.79),
        (_audit_mapping(), "search", "evalue", 0.01),
        (_split_mapping(component=True), "allocator", "class_balance_weight", 2.0),
    ],
)
def test_v020_protocol_rejects_changed_fixed_thresholds(
    tmp_path: Path,
    mapping: dict[str, Any],
    section: str,
    field: str,
    value: object,
) -> None:
    mapping[section][field] = value
    loader_name = (
        "load_cohort_config"
        if "selection" in mapping
        else "load_similarity_config"
        if "operation" in mapping
        else "load_split_config"
    )
    config_path = _write_yaml(tmp_path, "threshold.yaml", mapping)

    with pytest.raises(ValidationError, match=field):
        _load_v020(loader_name, config_path)


@pytest.mark.parametrize(
    ("name", "identity"),
    [("cluster50", 0.70), ("cluster70", 0.50)],
)
def test_derived_cluster_name_must_match_identity_threshold(
    tmp_path: Path, name: str, identity: float
) -> None:
    mapping = _cohort_cluster_derived_mapping(name=name, min_sequence_identity=identity)
    config_path = _write_yaml(tmp_path, "derived.yaml", mapping)

    with pytest.raises(ValidationError, match="threshold"):
        _load_v020("load_similarity_config", config_path)


def test_audit_strategy_and_violation_threshold_must_match_name(tmp_path: Path) -> None:
    mapping = _audit_mapping(name="cluster50", violation_identity_threshold=0.30)
    config_path = _write_yaml(tmp_path, "audit.yaml", mapping)

    with pytest.raises(ValidationError, match="violation_identity_threshold"):
        _load_v020("load_similarity_config", config_path)


@pytest.mark.parametrize(
    "ratios",
    [
        {"train": 0.69, "validation": 0.16, "test": 0.15},
        {"train": 0.70, "validation": 0.15, "test": 0.14},
    ],
)
def test_split_rejects_changed_or_non_unit_ratios(tmp_path: Path, ratios: dict[str, float]) -> None:
    mapping = _split_mapping(component=False)
    mapping["ratios"] = ratios
    config_path = _write_yaml(tmp_path, "ratios.yaml", mapping)

    with pytest.raises(ValidationError):
        _load_v020("load_split_config", config_path)


@pytest.mark.parametrize(
    ("loader_name", "mapping", "section"),
    [
        ("load_cohort_config", _cohort_mapping(), "selection"),
        ("load_split_config", _split_mapping(component=False), None),
    ],
)
def test_v020_configs_reject_changed_seed(
    tmp_path: Path,
    loader_name: str,
    mapping: dict[str, Any],
    section: str | None,
) -> None:
    target = mapping[section] if section is not None else mapping
    target["seed"] = 43
    config_path = _write_yaml(tmp_path, "seed.yaml", mapping)

    with pytest.raises(ValidationError, match="seed"):
        _load_v020(loader_name, config_path)


@pytest.mark.parametrize(
    ("loader_name", "mapping"),
    [
        ("load_cohort_config", _cohort_mapping()),
        ("load_similarity_config", _candidate_discovery_mapping()),
        ("load_split_config", _split_mapping(component=False)),
    ],
)
def test_v020_configs_accept_only_declared_run_modes(
    tmp_path: Path, loader_name: str, mapping: dict[str, Any]
) -> None:
    freeze_mapping = (
        _cohort_mapping(run_mode="freeze")
        if loader_name == "load_cohort_config"
        else deepcopy(mapping)
    )
    freeze_mapping["run_mode"] = "freeze"
    freeze_path = _write_yaml(tmp_path / "freeze", "config.yaml", freeze_mapping)
    assert _load_v020(loader_name, freeze_path).run_mode == "freeze"

    mapping["run_mode"] = "release"
    invalid_path = _write_yaml(tmp_path / "invalid", "config.yaml", mapping)
    with pytest.raises(ValidationError, match="run_mode"):
        _load_v020(loader_name, invalid_path)


@pytest.mark.parametrize(
    ("loader_name", "mapping"),
    [
        ("load_cohort_config", _cohort_mapping()),
        ("load_similarity_config", _candidate_discovery_mapping()),
        ("load_split_config", _split_mapping(component=False)),
    ],
)
def test_v020_configs_reject_overwrite(
    tmp_path: Path, loader_name: str, mapping: dict[str, Any]
) -> None:
    mapping["output"]["overwrite"] = True
    config_path = _write_yaml(tmp_path, "overwrite.yaml", mapping)

    with pytest.raises(ValidationError, match="overwrite"):
        _load_v020(loader_name, config_path)


@pytest.mark.parametrize(
    ("loader_name", "mapping", "source", "target"),
    [
        ("load_cohort_config", _cohort_mapping(), "cohort_manifest", "content_manifest"),
        (
            "load_similarity_config",
            _candidate_discovery_mapping(),
            "component_manifest",
            "pair_table",
        ),
        ("load_split_config", _split_mapping(component=False), "manifest", "content_manifest"),
    ],
)
def test_v020_configs_reject_output_path_collisions(
    tmp_path: Path,
    loader_name: str,
    mapping: dict[str, Any],
    source: str,
    target: str,
) -> None:
    mapping["output"][target] = mapping["output"][source]
    config_path = _write_yaml(tmp_path, "collision.yaml", mapping)

    with pytest.raises(ValidationError, match="distinct"):
        _load_v020(loader_name, config_path)


def test_random_split_rejects_component_only_fields(tmp_path: Path) -> None:
    mapping = _split_mapping(component=False)
    mapping["input"]["component_manifest"] = "../inputs/components.parquet"
    mapping["allocator"] = _split_mapping(component=True)["allocator"]
    config_path = _write_yaml(tmp_path, "random.yaml", mapping)

    with pytest.raises(ValidationError):
        _load_v020("load_split_config", config_path)
