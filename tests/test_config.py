# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from protein_split_audit.config import (
    CandidateSelectionConfig,
    SourceDownloadConfig,
    load_build_config,
    load_config,
    load_download_config,
)

PROJECT_ROOT = Path(__file__).parents[1]


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
