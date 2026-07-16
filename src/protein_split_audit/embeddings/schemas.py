# SPDX-License-Identifier: Apache-2.0

"""Strict schemas for frozen ESM-2 snapshots and extraction."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
REVISION_PATTERN = r"^[0-9a-f]{40}$"

APPROVED_MODEL_IDENTITIES: dict[str, tuple[str, str, str, int]] = {
    "esm2_35m": (
        "facebook/esm2_t12_35M_UR50D",
        "6fbf070e65b0b7291e7bbcd451118c216cff79d8",
        "e35647818e0e064351d4531ed480d225a002567b4b2b93ad3a9246d753150fc0",
        4096,
    ),
    "esm2_150m": (
        "facebook/esm2_t30_150M_UR50D",
        "a695f6045e2e32885fa60af20c13cb35398ce30c",
        "c3f1da8aea53bddd32c246c86168c23b9fd72341fb9db9a94436f855f5053566",
        2048,
    ),
}


class EmbeddingModelConfig(BaseModel):
    """One approved repository and immutable local snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str
    revision: str
    tokenizer_revision: str
    expected_weight_sha256: str = Field(pattern=SHA256_PATTERN)
    snapshot_root: Path

    @field_validator("revision", "tokenizer_revision")
    @classmethod
    def require_immutable_revision(cls, value: str) -> str:
        """Require a complete lowercase hexadecimal commit identity."""

        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("revision must be a 40-character immutable revision")
        return value


class RepresentationConfig(BaseModel):
    """Frozen representation rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: Literal["last"]
    pooling: Literal["residue_mean"]
    exclude_special_tokens: Literal[True]


class EmbeddingSequenceConfig(BaseModel):
    """Frozen sequence bounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_length: Literal[50]
    maximum_length: Literal[1000]
    truncation: Literal[False]


class EmbeddingBatchingConfig(BaseModel):
    """Deterministic padded-token batching policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_padded_tokens: int = Field(gt=0)
    ordering: Literal["encoded_length_then_sequence_sha256"]


class EmbeddingRuntimeConfig(BaseModel):
    """Formal or explicitly nonformal embedding runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formal: bool
    operating_system: str
    architecture: str
    device: Literal["cpu", "mps"]
    dtype: Literal["float32"]
    torch_intraop_threads: int = Field(ge=1)
    torch_interop_threads: int = Field(ge=1)
    deterministic_algorithms: bool
    local_files_only: bool

    @model_validator(mode="after")
    def require_canonical_formal_runtime(self) -> EmbeddingRuntimeConfig:
        """Reject drift in the approved formal platform contract."""

        if self.formal and (
            self.operating_system != "Darwin"
            or self.architecture != "arm64"
            or self.device != "cpu"
            or self.torch_intraop_threads != 8
            or self.torch_interop_threads != 1
            or not self.deterministic_algorithms
            or not self.local_files_only
        ):
            raise ValueError("formal runtime must be Darwin/arm64 CPU float32 with 8/1 threads")
        return self


class EmbeddingCacheConfig(BaseModel):
    """Local immutable embedding-cache policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    refuse_overwrite: Literal[True]


class EmbeddingConfig(BaseModel):
    """Complete frozen ESM-2 embedding definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    model_id: Literal["esm2_35m", "esm2_150m"]
    model: EmbeddingModelConfig
    representation: RepresentationConfig
    sequence: EmbeddingSequenceConfig
    batching: EmbeddingBatchingConfig
    runtime: EmbeddingRuntimeConfig
    cache: EmbeddingCacheConfig

    @model_validator(mode="after")
    def require_approved_identity(self) -> EmbeddingConfig:
        """Bind each model ID to its approved immutable identity and budget."""

        repository, revision, weight_sha256, budget = APPROVED_MODEL_IDENTITIES[self.model_id]
        if len(self.model.revision) != 40:
            raise ValueError("model revision must be a 40-character immutable revision")
        if self.model.repository != repository or self.model.revision != revision:
            raise ValueError("model must use the approved repository and immutable revision")
        if self.model.tokenizer_revision != self.model.revision:
            raise ValueError("model and tokenizer revisions must match")
        if self.model.expected_weight_sha256 != weight_sha256:
            raise ValueError("model must use the approved weight SHA-256")
        if self.batching.max_padded_tokens != budget:
            raise ValueError("model must use its approved padded-token budget")
        return self


class SnapshotFile(BaseModel):
    """One exact file in an acquired model snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=SHA256_PATTERN)
    repository: str
    revision: str = Field(pattern=REVISION_PATTERN)
    downloaded_at_utc: datetime


class ModelSnapshotManifest(BaseModel):
    """Sanitized identity for one exact five-file local snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_version: Literal[1] = 1
    model_id: Literal["esm2_35m", "esm2_150m"]
    repository: str
    revision: str = Field(pattern=REVISION_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    tokenizer_sha256: str = Field(pattern=SHA256_PATTERN)
    model_weight_sha256: str = Field(pattern=SHA256_PATTERN)
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)
    files: tuple[SnapshotFile, ...]


class EmbeddingBatchingManifest(BaseModel):
    """Aggregate deterministic batching facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_count: int = Field(ge=1)
    maximum_batch_size: int = Field(ge=1)
    maximum_encoded_length: int = Field(ge=1)
    maximum_padded_token_cost: int = Field(ge=1)
    mean_padded_token_cost: float = Field(gt=0)
    padding_efficiency: float = Field(gt=0, le=1)
    over_budget_singleton_count: int = Field(ge=0)


class EmbeddingManifest(BaseModel):
    """Timestamp-free identity and integrity data for one embedding cache."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_version: Literal[1] = 1
    cache_key: str = Field(pattern=SHA256_PATTERN)
    identity: dict[str, object]
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)
    matrix_file_sha256: str = Field(pattern=SHA256_PATTERN)
    matrix_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    index_file_sha256: str = Field(pattern=SHA256_PATTERN)
    row_count: int = Field(ge=1)
    hidden_size: int = Field(ge=1)
    dtype: Literal["float32"]
    split_name: Literal["random", "cluster70", "cluster50", "cluster30"]
    partitions: tuple[Literal["train", "validation"], Literal["train", "validation"]]
    partition_counts: dict[str, int]
    batching: EmbeddingBatchingManifest
    loading_class: Literal["transformers.EsmForMaskedLM"]
    feature_module: Literal["esm"]
    loading_info: dict[str, tuple[str, ...]]
    test_sequence_count_processed: Literal[0]
    test_labels_accessed: Literal[0]
    test_metrics_generated: Literal[0]
    implementation_version: Literal["esm-residue-mean-v1"]


__all__ = [
    "APPROVED_MODEL_IDENTITIES",
    "EmbeddingConfig",
    "EmbeddingManifest",
    "ModelSnapshotManifest",
    "SnapshotFile",
]
