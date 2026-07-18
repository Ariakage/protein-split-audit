# SPDX-License-Identifier: Apache-2.0

"""Validated project-foundation configuration loading."""

from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from protein_split_audit.cohort.schemas import (
    CohortConfig,
    DevelopmentCohortConfig,
    FreezeCohortConfig,
)
from protein_split_audit.embeddings.schemas import EmbeddingConfig
from protein_split_audit.experiments.schemas import (
    EsmExperimentConfig,
    ExperimentConfig,
    FrozenTestExperimentConfig,
)
from protein_split_audit.features.schemas import FeatureConfig
from protein_split_audit.models.schemas import ModelConfig
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes
from protein_split_audit.similarity.schemas import (
    AuditConfig,
    CandidateDiscoveryConfig,
    CohortClusterBaseConfig,
    CohortClusterDerivedConfig,
    SimilarityConfig,
)
from protein_split_audit.splits.schemas import SplitConfig

_SIMILARITY_CONFIG_ADAPTER: TypeAdapter[SimilarityConfig] = TypeAdapter(SimilarityConfig)
_COHORT_CONFIG_ADAPTER: TypeAdapter[CohortConfig] = TypeAdapter(CohortConfig)
_SPLIT_CONFIG_ADAPTER: TypeAdapter[SplitConfig] = TypeAdapter(SplitConfig)
_MODEL_CONFIG_ADAPTER: TypeAdapter[ModelConfig] = TypeAdapter(ModelConfig)
_COHORT_PATH_FIELDS = (
    (
        "input",
        (
            "candidate_dataset",
            "candidate_fasta",
            "raw_download",
            "build_manifest",
            "download_manifest",
            "discovery_components",
            "discovery_content_manifest",
            "difference_report",
            "review_attestation",
        ),
    ),
    ("output", ("cohort_manifest", "content_manifest", "fasta", "run_dir")),
)
_SIMILARITY_PATH_FIELDS = (
    ("runtime", ("cache_root",)),
    (
        "input",
        (
            "candidate_dataset",
            "build_manifest",
            "fasta",
            "cohort_manifest",
            "cohort_content_manifest",
            "base_pair_table",
            "base_pair_content_manifest",
            "split_manifest",
            "split_content_manifest",
            "cohort_fasta",
        ),
    ),
    (
        "output",
        (
            "component_manifest",
            "cluster_manifest",
            "content_manifest",
            "pair_table",
            "train_fasta",
            "test_fasta",
            "audit_manifest",
            "summary",
            "run_dir",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SimilarityConfigDocument:
    """Exact, logical, and resolved views of one similarity configuration."""

    source_path: Path
    source_bytes: bytes
    source_sha256: str
    logical_mapping: Mapping[str, object]
    effective_sha256: str
    config: SimilarityConfig

    def __post_init__(self) -> None:
        """Detach and deeply freeze the public logical snapshot."""

        object.__setattr__(self, "logical_mapping", _freeze_logical_mapping(self.logical_mapping))


@dataclass(frozen=True, slots=True)
class CohortConfigDocument:
    """Exact, logical, and resolved views of one cohort configuration."""

    source_path: Path
    source_bytes: bytes
    source_sha256: str
    logical_mapping: Mapping[str, object]
    effective_sha256: str
    config: DevelopmentCohortConfig | FreezeCohortConfig

    def __post_init__(self) -> None:
        """Detach and deeply freeze the public logical snapshot."""

        object.__setattr__(self, "logical_mapping", _freeze_logical_mapping(self.logical_mapping))


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
    if isinstance(value, Path):
        path = value
    elif isinstance(value, str):
        if not value.strip():
            raise ValueError("path value must not be blank")
        path = Path(value)
    else:
        raise ValueError("path value must be a string or pathlib.Path")
    path = path.expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _load_yaml_mapping(path: Path) -> tuple[Path, bytes, dict[str, Any]]:
    config_path = path.expanduser().resolve()
    source_bytes = config_path.read_bytes()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("configuration must be valid UTF-8") from error
    try:
        loaded: Any = yaml.safe_load(source_text)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML configuration: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError("configuration root must be a mapping")
    return config_path, source_bytes, loaded


def _resolve_section_paths(
    loaded: dict[str, Any],
    section: str,
    path_fields: tuple[str, ...],
    base_dir: Path,
) -> None:
    """Resolve declared path fields in one nested configuration mapping."""

    raw_section = loaded.get(section)
    if not isinstance(raw_section, dict):
        return
    for field in path_fields:
        if field in raw_section:
            raw_section[field] = _resolve_path(raw_section[field], base_dir)


def _resolve_runtime_executable(loaded: dict[str, Any], base_dir: Path) -> None:
    """Resolve explicit executable paths while preserving PATH-discovered names."""

    raw_runtime = loaded.get("runtime")
    if not isinstance(raw_runtime, dict):
        return
    raw_executable = raw_runtime.get("executable")
    if not isinstance(raw_executable, str) or not raw_executable.strip():
        return
    requested = raw_executable.strip()
    candidate = Path(requested).expanduser()
    is_explicit_path = (
        candidate.is_absolute() or candidate.name != requested or requested in {".", ".."}
    )
    raw_runtime["executable"] = (
        str(_resolve_path(requested, base_dir)) if is_explicit_path else requested
    )


def _config_relative_posix(path: Path, base_dir: Path) -> str:
    return Path(os.path.relpath(path, start=base_dir)).as_posix()


def _logical_effective_similarity_mapping(
    config: SimilarityConfig,
    source_mapping: Mapping[str, object],
    base_dir: Path,
) -> dict[str, object]:
    effective: dict[str, Any] = config.model_dump(mode="python")
    for section, fields in _SIMILARITY_PATH_FIELDS:
        raw_section = effective.get(section)
        if not isinstance(raw_section, dict):
            continue
        for field in fields:
            value = raw_section.get(field)
            if isinstance(value, Path):
                raw_section[field] = _config_relative_posix(value, base_dir)

    runtime = effective["runtime"]
    if not isinstance(runtime, dict):
        raise AssertionError("validated similarity runtime must be a mapping")
    executable = config.runtime.executable
    if Path(executable).is_absolute():
        source_runtime = source_mapping.get("runtime")
        source_executable = (
            source_runtime.get("executable") if isinstance(source_runtime, Mapping) else None
        )
        requested = source_executable.strip() if isinstance(source_executable, str) else ""
        if requested and not Path(requested).expanduser().is_absolute():
            runtime["executable"] = requested
        else:
            runtime["executable"] = _config_relative_posix(Path(executable), base_dir)
    return effective


def _logical_effective_cohort_mapping(
    config: DevelopmentCohortConfig | FreezeCohortConfig,
    base_dir: Path,
) -> dict[str, object]:
    effective: dict[str, Any] = config.model_dump(mode="python")
    for section, fields in _COHORT_PATH_FIELDS:
        raw_section = effective.get(section)
        if not isinstance(raw_section, dict):
            continue
        for field in fields:
            value = raw_section.get(field)
            if isinstance(value, Path):
                raw_section[field] = _config_relative_posix(value, base_dir)
    return effective


def _freeze_logical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_logical_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_logical_value(item) for item in value)
    return value


def _freeze_logical_mapping(mapping: Mapping[str, object]) -> Mapping[str, object]:
    frozen = _freeze_logical_value(mapping)
    if not isinstance(frozen, Mapping):
        raise AssertionError("logical similarity configuration must be a mapping")
    return frozen


def load_config(path: Path) -> ProjectConfig:
    """Load YAML configuration with paths relative to the config file."""

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)

    raw_paths = loaded.get("paths")
    if isinstance(raw_paths, dict):
        loaded["paths"] = {
            key: _resolve_path(value, config_path.parent) for key, value in raw_paths.items()
        }
    return ProjectConfig.model_validate(loaded)


def load_download_config(path: Path) -> DownloadConfig:
    """Load a UniProt download config with config-relative output paths."""

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)
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

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)
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


def load_cohort_config_document(path: Path) -> CohortConfigDocument:
    """Load exact, logical, and resolved views of one cohort configuration."""

    config_path, source_bytes, loaded = _load_yaml_mapping(path)
    for section, fields in _COHORT_PATH_FIELDS:
        _resolve_section_paths(loaded, section, fields, config_path.parent)
    config = _COHORT_CONFIG_ADAPTER.validate_python(loaded)
    logical_mapping = _freeze_logical_mapping(
        _logical_effective_cohort_mapping(config, config_path.parent)
    )
    return CohortConfigDocument(
        source_path=config_path,
        source_bytes=source_bytes,
        source_sha256=sha256_bytes(source_bytes),
        logical_mapping=logical_mapping,
        effective_sha256=sha256_bytes(serialize_canonical_json(logical_mapping)),
        config=config,
    )


def load_cohort_config(path: Path) -> DevelopmentCohortConfig | FreezeCohortConfig:
    """Load a cohort config with all artifact paths relative to its YAML file."""

    return load_cohort_config_document(path).config


def load_similarity_config_document(path: Path) -> SimilarityConfigDocument:
    """Load exact, logical, and resolved views of one similarity operation."""

    config_path, source_bytes, loaded = _load_yaml_mapping(path)
    source_mapping = deepcopy(loaded)
    for section, fields in _SIMILARITY_PATH_FIELDS:
        _resolve_section_paths(loaded, section, fields, config_path.parent)
    _resolve_runtime_executable(loaded, config_path.parent)
    config = _SIMILARITY_CONFIG_ADAPTER.validate_python(loaded)
    logical_mapping = _freeze_logical_mapping(
        _logical_effective_similarity_mapping(config, source_mapping, config_path.parent)
    )
    return SimilarityConfigDocument(
        source_path=config_path,
        source_bytes=source_bytes,
        source_sha256=sha256_bytes(source_bytes),
        logical_mapping=logical_mapping,
        effective_sha256=sha256_bytes(serialize_canonical_json(logical_mapping)),
        config=config,
    )


def load_similarity_config(
    path: Path,
) -> CandidateDiscoveryConfig | CohortClusterBaseConfig | CohortClusterDerivedConfig | AuditConfig:
    """Load and discriminate one config-relative similarity operation."""

    return load_similarity_config_document(path).config


def load_split_config(path: Path) -> SplitConfig:
    """Load and discriminate one config-relative split strategy."""

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)
    _resolve_section_paths(
        loaded,
        "input",
        (
            "cohort_manifest",
            "cohort_content_manifest",
            "component_manifest",
            "component_content_manifest",
        ),
        config_path.parent,
    )
    _resolve_section_paths(
        loaded,
        "output",
        ("manifest", "content_manifest", "run_dir"),
        config_path.parent,
    )
    return _SPLIT_CONFIG_ADAPTER.validate_python(loaded)


def load_feature_config(path: Path) -> FeatureConfig:
    """Load one frozen classical feature definition."""

    _config_path, _source_bytes, loaded = _load_yaml_mapping(path)
    return FeatureConfig.model_validate(loaded)


def load_embedding_config(path: Path) -> EmbeddingConfig:
    """Load one frozen ESM-2 definition with config-relative local paths."""

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)
    _resolve_section_paths(loaded, "model", ("snapshot_root",), config_path.parent)
    _resolve_section_paths(loaded, "cache", ("root",), config_path.parent)
    return EmbeddingConfig.model_validate(loaded)


def load_model_config(path: Path) -> ModelConfig:
    """Load and discriminate one frozen classical model definition."""

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)
    if loaded.get("type") == "nearest_homolog":
        _resolve_section_paths(loaded, "runtime", ("cache_root",), config_path.parent)
        _resolve_runtime_executable(loaded, config_path.parent)
    return _MODEL_CONFIG_ADAPTER.validate_python(loaded)


def _resolve_frozen_test_path(value: object, base_dir: Path, project_root: Path) -> Path:
    """Resolve one v0.5 path while rejecting absolute and escaping values."""

    if not isinstance(value, (str, Path)):
        raise ValueError("frozen Test path value must be a string or pathlib.Path")
    raw = Path(value).expanduser()
    if raw.is_absolute():
        raise ValueError("frozen Test paths must be project-relative")
    resolved = (base_dir / raw).resolve()
    if not resolved.is_relative_to(project_root):
        raise ValueError("frozen Test paths must remain inside the project root")
    return resolved


def _load_frozen_test_experiment(
    loaded: dict[str, Any],
    config_path: Path,
) -> FrozenTestExperimentConfig:
    """Resolve the strict v0.5 configuration without accepting path overrides."""

    if config_path.parent.name != "experiment" or config_path.parent.parent.name != "configs":
        raise ValueError("frozen Test configuration must live under configs/experiment")
    base = config_path.parent
    project_root = config_path.parents[2]

    def resolve(value: object) -> Path:
        return _resolve_frozen_test_path(value, base, project_root)

    raw_cohort = loaded.get("cohort")
    if isinstance(raw_cohort, dict):
        for field in ("manifest", "content_manifest", "fasta"):
            if field in raw_cohort:
                raw_cohort[field] = resolve(raw_cohort[field])
    for section, fields in (
        ("splits", ("manifest", "content_manifest")),
        ("methods", ("feature_config", "model_config", "embedding_config")),
        ("model_snapshots", ("manifest",)),
        ("tracked_evidence", ("path",)),
    ):
        entries = loaded.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for field in fields:
                if entry.get(field) is not None:
                    entry[field] = resolve(entry[field])
    raw_outputs = loaded.get("outputs")
    if isinstance(raw_outputs, dict) and raw_outputs.get("root") is not None:
        raw_outputs["root"] = resolve(raw_outputs["root"])
    if loaded.get("attestation") is not None:
        loaded["attestation"] = resolve(loaded["attestation"])

    config = FrozenTestExperimentConfig.model_validate(loaded)
    if config.outputs.root != project_root / "results/runs/v0.5.0-test-r1":
        raise ValueError("outputs.root must be the fixed v0.5 r1 Test run root")
    if config.attestation != project_root / "docs/attestations/v0.5.0-test-freeze-r1.yaml":
        raise ValueError("attestation must be the fixed v0.5 r1 Test-freeze path")
    return config


def load_experiment_config(
    path: Path,
) -> ExperimentConfig | EsmExperimentConfig | FrozenTestExperimentConfig:
    """Load a config-relative validation matrix or denied Test request."""

    config_path, _source_bytes, loaded = _load_yaml_mapping(path)
    if loaded.get("experiment_type") == "frozen_test":
        return _load_frozen_test_experiment(loaded, config_path)
    base = config_path.parent
    _resolve_section_paths(loaded, "cohort", ("manifest", "content_manifest", "fasta"), base)
    raw_splits = loaded.get("splits")
    if isinstance(raw_splits, list):
        for item in raw_splits:
            if isinstance(item, dict):
                for field in ("manifest", "content_manifest"):
                    if field in item:
                        item[field] = _resolve_path(item[field], base)
    raw_baselines = loaded.get("baselines")
    if isinstance(raw_baselines, list):
        for item in raw_baselines:
            if isinstance(item, dict):
                for field in ("feature_config", "model_config"):
                    if item.get(field) is not None:
                        item[field] = _resolve_path(item[field], base)
    raw_models = loaded.get("models")
    if isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, dict) and item.get("embedding_config") is not None:
                item["embedding_config"] = _resolve_path(item["embedding_config"], base)
    if loaded.get("linear_probe_config") is not None:
        loaded["linear_probe_config"] = _resolve_path(loaded["linear_probe_config"], base)
    _resolve_section_paths(loaded, "outputs", ("root",), base)
    if loaded.get("attestation") is not None:
        loaded["attestation"] = _resolve_path(loaded["attestation"], base)
    if loaded.get("experiment_type") == "esm2_validation":
        return EsmExperimentConfig.model_validate(loaded)
    return ExperimentConfig.model_validate(loaded)
