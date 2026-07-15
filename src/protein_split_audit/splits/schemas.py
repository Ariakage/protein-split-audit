# SPDX-License-Identifier: Apache-2.0

"""Validated configuration schemas for deterministic dataset splits."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_fixed_floats(values: tuple[tuple[str, float, float], ...]) -> None:
    """Reject changes to protocol-fixed floating-point values."""

    for field_name, value, expected in values:
        if value != expected:
            raise ValueError(f"{field_name} must be {expected}")


class SequenceSplitInputConfig(_FrozenConfig):
    """Cohort inputs for a sequence-stratified random split."""

    cohort_manifest: Path
    cohort_content_manifest: Path


class ComponentSplitInputConfig(SequenceSplitInputConfig):
    """Additional component inputs for whole-component allocation."""

    component_manifest: Path
    component_content_manifest: Path


class SplitRatios(_FrozenConfig):
    """The fixed 70/15/15 split ratios."""

    train: float
    validation: float
    test: float

    @model_validator(mode="after")
    def ratios_must_sum_exactly_to_one(self) -> SplitRatios:
        """Check the ratio sum using decimal rather than binary arithmetic."""

        total = sum(
            (Decimal(str(value)) for value in (self.train, self.validation, self.test)),
            start=Decimal(0),
        )
        if total != Decimal("1.0"):
            raise ValueError("split ratios must sum exactly to 1.0")
        _require_fixed_floats(
            (
                ("train", self.train, 0.70),
                ("validation", self.validation, 0.15),
                ("test", self.test, 0.15),
            )
        )
        return self


class AllocatorConfig(_FrozenConfig):
    """Fixed loss weights for whole-component allocation."""

    version: Literal["greedy_component_loss_v1"]
    size_weight: float
    class_balance_weight: float
    group_count_weight: float
    missing_class_weight: float

    @model_validator(mode="after")
    def weights_must_match_protocol(self) -> AllocatorConfig:
        """Keep the allocator loss function stable."""

        _require_fixed_floats(
            (
                ("size_weight", self.size_weight, 1.0),
                ("class_balance_weight", self.class_balance_weight, 3.0),
                ("group_count_weight", self.group_count_weight, 0.5),
                ("missing_class_weight", self.missing_class_weight, 10.0),
            )
        )
        return self


class SplitOutputConfig(_FrozenConfig):
    """Non-overwriting destinations for split artifacts."""

    manifest: Path
    content_manifest: Path
    run_dir: Path
    overwrite: Literal[False] = False

    @model_validator(mode="after")
    def output_paths_must_be_distinct(self) -> SplitOutputConfig:
        """Prevent exact destination collisions."""

        paths = (self.manifest, self.content_manifest, self.run_dir)
        if len(set(paths)) != len(paths):
            raise ValueError("split output paths must be distinct")
        return self


class _SplitConfigBase(_FrozenConfig):
    schema_version: Literal[1]
    name: str
    strategy: str
    run_mode: Literal["development", "freeze"]
    ratios: SplitRatios
    seed: Literal[42]
    stratify_by: Literal["ec_level_2"]
    ratio_tolerance: float
    output: SplitOutputConfig

    @model_validator(mode="after")
    def tolerance_must_match_protocol(self) -> Self:
        """Keep the visible split-ratio tolerance fixed."""

        _require_fixed_floats((("ratio_tolerance", self.ratio_tolerance, 0.05),))
        return self


class SequenceStratifiedSplitConfig(_SplitConfigBase):
    """Configuration for stable per-class sequence assignment."""

    name: Literal["random"]
    strategy: Literal["sequence_stratified"]
    input: SequenceSplitInputConfig


class SimilarityComponentSplitConfig(_SplitConfigBase):
    """Configuration for whole-component split allocation."""

    name: Literal["cluster70", "cluster50", "cluster30"]
    strategy: Literal["similarity_component"]
    input: ComponentSplitInputConfig
    allocator: AllocatorConfig


type SplitConfig = Annotated[
    SequenceStratifiedSplitConfig | SimilarityComponentSplitConfig,
    Field(discriminator="strategy"),
]


__all__ = [
    "AllocatorConfig",
    "ComponentSplitInputConfig",
    "SequenceSplitInputConfig",
    "SequenceStratifiedSplitConfig",
    "SimilarityComponentSplitConfig",
    "SplitConfig",
    "SplitOutputConfig",
    "SplitRatios",
]
