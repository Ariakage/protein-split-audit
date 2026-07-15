# SPDX-License-Identifier: Apache-2.0

"""Validated configuration schemas for auditable cohort selection."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from protein_split_audit.provenance import BuildManifest
from protein_split_audit.splits.schemas import AllocatorConfig, SplitRatios

SELECTION_RULE_VERSION = "pilot-ec2-5class-min40-c30g10-cap250-seed42-v1"


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateRecord(_FrozenConfig):
    """One validated candidate with the source accession mapped to its public name."""

    accession: str
    entry_name: str
    protein_name: str
    organism_name: str
    organism_id: int
    sequence: str
    sequence_length: int = Field(ge=0)
    sequence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ec_number: str
    ec_level_2: str
    duplicate_count: int = Field(ge=1)
    duplicate_accessions: tuple[str, ...]
    source_page_number: int = Field(ge=1)
    source_row_number: int = Field(ge=1)


class CandidatePool(_FrozenConfig):
    """Verified candidate records and hashes for their three explicit inputs."""

    records: tuple[CandidateRecord, ...]
    build_manifest: BuildManifest = Field(exclude=True)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fasta_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateClassCount(_FrozenConfig):
    """Aggregate candidate count for one EC-level-2 label."""

    ec_level_2: str
    candidate_count: int = Field(ge=1)


class SequenceLengthSummary(_FrozenConfig):
    """Deterministic descriptive statistics over candidate sequence lengths."""

    count: int = Field(ge=0)
    maximum: int | None
    mean: float | None
    median: float | None
    minimum: int | None
    quantiles: dict[str, float | None]


class CandidatePoolProfile(_FrozenConfig):
    """Sequence-free aggregate profile tied to verified candidate inputs."""

    profile_schema_version: Literal[1] = 1
    candidate_count: int = Field(ge=0)
    ec_level_2_class_counts: tuple[CandidateClassCount, ...]
    sequence_length_summary: SequenceLengthSummary
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fasta_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CohortInputConfig(_FrozenConfig):
    """Inputs needed to profile and select a cohort."""

    candidate_dataset: Path
    candidate_fasta: Path
    raw_download: Path
    build_manifest: Path
    download_manifest: Path
    discovery_components: Path
    discovery_content_manifest: Path


class FreezeCohortInputConfig(CohortInputConfig):
    """Additional reviewed evidence required by a future freeze run."""

    difference_report: Path
    review_attestation: Path


class CohortSelectionConfig(_FrozenConfig):
    """Maintainer-approved deterministic Pilot Cohort protocol."""

    selection_rule_version: Literal["pilot-ec2-5class-min40-c30g10-cap250-seed42-v1"]
    label_field: Literal["ec_level_2"]
    min_sequences_per_class: Literal[40]
    min_groups_per_class_at_cluster30: Literal[10]
    max_sequences_per_class: Literal[250]
    number_of_classes: Literal[5]
    seed: Literal[42]
    class_ranking: Literal["capped_count_desc_group_count_desc_label_asc_v1"]
    member_ranking: Literal["component_round_robin_sha256_v1"]


class CohortFeasibilityConfig(_FrozenConfig):
    """Fixed component-allocation preflight protocol for cohort selection."""

    ratios: SplitRatios
    ratio_tolerance: float
    allocator: AllocatorConfig

    @model_validator(mode="after")
    def tolerance_must_match_protocol(self) -> CohortFeasibilityConfig:
        """Keep the feasibility ratio tolerance fixed at five percentage points."""

        if self.ratio_tolerance != 0.05:
            raise ValueError("ratio_tolerance must be 0.05")
        return self


class CohortOutputConfig(_FrozenConfig):
    """Non-overwriting destinations for cohort artifacts."""

    cohort_manifest: Path
    content_manifest: Path
    fasta: Path
    run_dir: Path
    overwrite: Literal[False] = False

    @model_validator(mode="after")
    def output_paths_must_be_distinct(self) -> CohortOutputConfig:
        """Prevent two configured artifacts from sharing a destination."""

        paths = (self.cohort_manifest, self.content_manifest, self.fasta, self.run_dir)
        if len(set(paths)) != len(paths):
            raise ValueError("cohort output paths must be distinct")
        return self


class _CohortConfigBase(_FrozenConfig):
    """Fields shared by provisional selection and a future reviewed freeze."""

    schema_version: Literal[1]
    selection: CohortSelectionConfig
    feasibility: CohortFeasibilityConfig
    output: CohortOutputConfig


class DevelopmentCohortConfig(_CohortConfigBase):
    """Provisional cohort selection that cannot claim the pilot-v1 identity."""

    cohort_version: Literal["pilot-v1-candidate"]
    run_mode: Literal["development"]
    input: CohortInputConfig


class FreezeCohortConfig(_CohortConfigBase):
    """Configuration shape for a later explicitly reviewed pilot-v1 freeze."""

    cohort_version: Literal["pilot-v1"]
    run_mode: Literal["freeze"]
    input: FreezeCohortInputConfig


type CohortConfig = Annotated[
    DevelopmentCohortConfig | FreezeCohortConfig,
    Field(discriminator="run_mode"),
]


__all__ = [
    "SELECTION_RULE_VERSION",
    "CandidateClassCount",
    "CandidatePool",
    "CandidatePoolProfile",
    "CandidateRecord",
    "CohortConfig",
    "CohortFeasibilityConfig",
    "CohortInputConfig",
    "CohortOutputConfig",
    "CohortSelectionConfig",
    "DevelopmentCohortConfig",
    "FreezeCohortConfig",
    "FreezeCohortInputConfig",
    "SequenceLengthSummary",
]
