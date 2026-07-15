# SPDX-License-Identifier: Apache-2.0

"""Strict configuration and artifact schemas for classical features."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


class FeaturePreprocessing(BaseModel):
    """Explicit preprocessing choice for one feature representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scaler: Literal["standard_train_only", "none"]


class FeatureConfig(BaseModel):
    """Frozen v0.3.0 feature definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    name: Literal["length", "aac", "kmer3"]
    kind: Literal["length", "aac", "kmer3"]
    implementation_version: Literal["length-v1", "aac20-v1", "kmer3-fixed8000-relative-v1"]
    alphabet: Literal["ACDEFGHIKLMNPQRSTVWY"] = "ACDEFGHIKLMNPQRSTVWY"
    feature_count: Literal[1, 20, 8000]
    dtype: Literal["float64"]
    normalization: Literal["none", "sequence_length", "relative_frequency"]
    k: Literal[3] | None = None
    vocabulary: Literal["fixed_complete"] | None = None
    sparse_format: Literal["csr"] | None = None
    preprocessing: FeaturePreprocessing

    @model_validator(mode="after")
    def require_frozen_combination(self) -> FeatureConfig:
        """Reject any representation that differs from the reviewed protocol."""

        expected = {
            "length": ("length-v1", 1, "none", None, None, None, "standard_train_only"),
            "aac": ("aac20-v1", 20, "sequence_length", None, None, None, "standard_train_only"),
            "kmer3": (
                "kmer3-fixed8000-relative-v1",
                8000,
                "relative_frequency",
                3,
                "fixed_complete",
                "csr",
                "none",
            ),
        }[self.kind]
        observed = (
            self.implementation_version,
            self.feature_count,
            self.normalization,
            self.k,
            self.vocabulary,
            self.sparse_format,
            self.preprocessing.scaler,
        )
        if observed != expected:
            if self.kind == "kmer3" and self.preprocessing.scaler != "none":
                raise ValueError("kmer3 requires scaler none")
            raise ValueError(f"{self.kind} configuration differs from the frozen protocol")
        if self.name != self.kind:
            raise ValueError("feature name and kind must match")
        return self


__all__ = ["ALPHABET", "FeatureConfig", "FeaturePreprocessing"]
