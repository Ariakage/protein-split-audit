# SPDX-License-Identifier: Apache-2.0

"""Validated project-foundation configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ProjectPaths(BaseModel):
    """Filesystem locations used by project-foundation commands."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path
    cache_dir: Path
    results_dir: Path


class ProjectConfig(BaseModel):
    """Versioned foundation configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    paths: ProjectPaths


class DownloadField(BaseModel):
    """One requested UniProt field and its expected TSV heading."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    response_header: str = Field(min_length=1)
    required: bool = True


class SourceDownloadConfig(BaseModel):
    """UniProt source-request settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    database: Literal["UniProtKB/Swiss-Prot"]
    endpoint: AnyHttpUrl
    query: str = Field(min_length=1)
    format: Literal["tsv"] = "tsv"
    fields: tuple[DownloadField, ...] = Field(min_length=1)
    page_size: int = Field(ge=1, le=500)
    timeout_seconds: float = Field(gt=0)

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_be_approved(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        """Restrict downloads to the credential-free UniProtKB search endpoint."""

        if (
            value.scheme != "https"
            or value.host != "rest.uniprot.org"
            or (value.path or "").rstrip("/") != "/uniprotkb/search"
            or value.port not in {None, 443}
            or value.username is not None
            or value.password is not None
        ):
            raise ValueError("endpoint must be the approved UniProtKB HTTPS endpoint")
        return value

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        """Reject queries containing only whitespace."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped

    @model_validator(mode="after")
    def fields_must_be_unique(self) -> SourceDownloadConfig:
        """Reject ambiguous request names or TSV headings."""

        names = self.requested_fields
        headers = self.expected_response_headers
        if len(set(names)) != len(names):
            raise ValueError("requested field names must be unique")
        if len(set(headers)) != len(headers):
            raise ValueError("response headers must be unique")
        return self

    @property
    def requested_fields(self) -> tuple[str, ...]:
        """Return field identifiers in request order."""

        return tuple(field.name for field in self.fields)

    @property
    def expected_response_headers(self) -> tuple[str, ...]:
        """Return expected TSV headings in request order."""

        return tuple(field.response_header for field in self.fields)

    @property
    def required_response_headers(self) -> tuple[str, ...]:
        """Return required TSV headings."""

        return tuple(field.response_header for field in self.fields if field.required)


class RetryConfig(BaseModel):
    """Bounded retry policy for transient download failures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retries: int = Field(ge=0, le=10)
    backoff_initial_seconds: float = Field(gt=0)
    backoff_max_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def maximum_must_cover_initial_delay(self) -> RetryConfig:
        """Ensure the exponential schedule can start within its cap."""

        if self.backoff_max_seconds < self.backoff_initial_seconds:
            raise ValueError("backoff_max_seconds must be at least backoff_initial_seconds")
        return self


class DownloadOutputConfig(BaseModel):
    """Local raw-data and tracked-manifest destinations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_dir: Path
    manifest_dir: Path
    compressed_filename: str = Field(min_length=1)
    manifest_filename: str = Field(min_length=1)
    overwrite: Literal[False] = False

    @field_validator("compressed_filename", "manifest_filename")
    @classmethod
    def filename_must_not_include_directories(cls, value: str) -> str:
        """Keep configured outputs inside their approved directories."""

        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("output filename must not include a directory")
        return value


class DownloadConfig(BaseModel):
    """Validated configuration for one UniProt download."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    run_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    source: SourceDownloadConfig
    retry: RetryConfig
    output: DownloadOutputConfig


class CandidateSelectionConfig(BaseModel):
    """Fixed biological eligibility rules for the v0.1.0 candidate dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_amino_acids: Literal["ACDEFGHIKLMNPQRSTVWY"]
    min_sequence_length: Literal[50]
    max_sequence_length: Literal[1000]
    require_single_ec: Literal[True]
    require_complete_ec: Literal[True]


class BuildOutputConfig(BaseModel):
    """Local candidate outputs and tracked, sequence-free audit destinations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    processed_dir: Path
    manifest_dir: Path
    parquet_filename: str = Field(min_length=1)
    fasta_filename: str = Field(min_length=1)
    manifest_filename: str = Field(min_length=1)
    deduplication_filename: str = Field(min_length=1)
    conflicts_filename: str = Field(min_length=1)
    rejections_filename: str = Field(min_length=1)
    overwrite: Literal[False] = False

    @field_validator(
        "parquet_filename",
        "fasta_filename",
        "manifest_filename",
        "deduplication_filename",
        "conflicts_filename",
        "rejections_filename",
    )
    @classmethod
    def filename_must_not_include_directories(cls, value: str) -> str:
        """Keep configured outputs inside their approved directories."""

        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("output filename must not include a directory")
        return value

    @model_validator(mode="after")
    def filenames_must_be_unique(self) -> BuildOutputConfig:
        """Prevent one configured artifact from replacing another in memory."""

        processed_names = (self.parquet_filename, self.fasta_filename)
        manifest_names = (
            self.manifest_filename,
            self.deduplication_filename,
            self.conflicts_filename,
            self.rejections_filename,
        )
        if len(set(processed_names)) != len(processed_names):
            raise ValueError("processed output filenames must be unique")
        if len(set(manifest_names)) != len(manifest_names):
            raise ValueError("manifest output filenames must be unique")
        return self


class BuildConfig(DownloadConfig):
    """Validated download parent and candidate-construction configuration."""

    candidate_selection: CandidateSelectionConfig
    build_output: BuildOutputConfig

    @model_validator(mode="after")
    def build_manifest_must_not_replace_download_manifest(self) -> BuildConfig:
        """Keep parent and child provenance distinct when directories coincide."""

        if (
            self.output.manifest_dir == self.build_output.manifest_dir
            and self.output.manifest_filename == self.build_output.manifest_filename
        ):
            raise ValueError("build manifest must differ from the download manifest")
        return self


def _resolve_path(value: object, base_dir: Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _load_yaml_mapping(path: Path) -> tuple[Path, dict[str, Any]]:
    config_path = path.expanduser().resolve()
    loaded: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("configuration root must be a mapping")
    return config_path, loaded


def load_config(path: Path) -> ProjectConfig:
    """Load YAML configuration with paths relative to the config file."""

    config_path, loaded = _load_yaml_mapping(path)

    raw_paths = loaded.get("paths")
    if isinstance(raw_paths, dict):
        loaded["paths"] = {
            key: _resolve_path(value, config_path.parent) for key, value in raw_paths.items()
        }
    return ProjectConfig.model_validate(loaded)


def load_download_config(path: Path) -> DownloadConfig:
    """Load a UniProt download config with config-relative output paths."""

    config_path, loaded = _load_yaml_mapping(path)
    raw_output = loaded.get("output")
    if isinstance(raw_output, dict):
        for key in ("raw_dir", "manifest_dir"):
            if key in raw_output:
                raw_output[key] = _resolve_path(raw_output[key], config_path.parent)
    download_keys = {"schema_version", "run_name", "source", "retry", "output"}
    download_mapping = {key: value for key, value in loaded.items() if key in download_keys}
    return DownloadConfig.model_validate(download_mapping)


def load_build_config(path: Path) -> BuildConfig:
    """Load candidate-build configuration with config-relative artifact paths."""

    config_path, loaded = _load_yaml_mapping(path)
    raw_download_output = loaded.get("output")
    if isinstance(raw_download_output, dict):
        for key in ("raw_dir", "manifest_dir"):
            if key in raw_download_output:
                raw_download_output[key] = _resolve_path(
                    raw_download_output[key], config_path.parent
                )

    raw_build_output = loaded.get("build_output")
    if isinstance(raw_build_output, dict):
        for key in ("processed_dir", "manifest_dir"):
            if key in raw_build_output:
                raw_build_output[key] = _resolve_path(raw_build_output[key], config_path.parent)
    return BuildConfig.model_validate(loaded)
