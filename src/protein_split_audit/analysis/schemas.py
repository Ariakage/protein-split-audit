# SPDX-License-Identifier: Apache-2.0

"""Strict schemas for the pre-specified v0.6 post-Test analysis."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
type MethodName = Literal[
    "majority",
    "length-logistic",
    "aac-logistic",
    "kmer3-logistic",
    "nearest-homolog",
    "esm2-35m",
    "esm2-150m",
]
type SplitName = Literal["random", "cluster70", "cluster50", "cluster30"]
type MetricName = Literal["accuracy", "balanced_accuracy", "macro_f1"]

METHODS: tuple[MethodName, ...] = (
    "majority",
    "length-logistic",
    "aac-logistic",
    "kmer3-logistic",
    "nearest-homolog",
    "esm2-35m",
    "esm2-150m",
)
SPLITS: tuple[SplitName, ...] = ("random", "cluster70", "cluster50", "cluster30")
LABEL_ORDER = ("2.7", "3.1", "1.1", "2.1", "4.1")

_PREDICTION_HASHES: dict[tuple[MethodName, SplitName], str] = {
    ("majority", "random"): "977701893196e98009ddc85c1fcf95ae2cf4734fc67bac80ff040672f4c4a909",
    ("majority", "cluster70"): "4808f69e3a618ce1a812cea758c1049b2d68c92b14116f75c307cfe32c4e4b9a",
    ("majority", "cluster50"): "d443ecdfaef8a1cc991719fa4cfeed00c7e25093f25265b796bd299a8f8578af",
    ("majority", "cluster30"): "00dac47ae2d6dbea7a00c9dbaf138192b540d0f5429fb785bf300f76dc95cbfb",
    (
        "length-logistic",
        "random",
    ): "d124cd7f27c285c74df5e084e172a0c89c23d7925bcf3404ece8fa41c392e468",
    (
        "length-logistic",
        "cluster70",
    ): "c76202e0293479dd646e922d37d3265c2ccb44e4f99693a71d7a3917b9d869d4",
    (
        "length-logistic",
        "cluster50",
    ): "177efa6fb8b6aec7f3e05c25261f7aaf8d9ab4115886c58f384a5540cf1f5eae",
    (
        "length-logistic",
        "cluster30",
    ): "651442d5a6b02238ed6bfea9b0d842e66541b59eb0a90d0484cea9cb4a29cf54",
    ("aac-logistic", "random"): "1817810409d03fb7b5c76bbfc159d832a4d1db42cefd78d56f43d175fa39ca24",
    (
        "aac-logistic",
        "cluster70",
    ): "c15d7ba3a0b31c571f5fc23d5851137a4915b447a68b06d401137865bed74271",
    (
        "aac-logistic",
        "cluster50",
    ): "3d032bce9bc8a96c82d2eba54f935b0aec9b47fb44c6d46d79b25e871305349a",
    (
        "aac-logistic",
        "cluster30",
    ): "c344eb7bc06382e31eec332ff16278bad80b43e7145bcdf30479960e2139dbaf",
    (
        "kmer3-logistic",
        "random",
    ): "677ff2f3165c2671a857cb6dcfdb9996d73df6280394718a89b39913a37d63ba",
    (
        "kmer3-logistic",
        "cluster70",
    ): "2f2cb9e7f7e28a3aeb42a4decdbbee5e5f87577e9184c205209d2a5361f74506",
    (
        "kmer3-logistic",
        "cluster50",
    ): "43da3eec12c7dd02c3d2a6df50ff625f3926f52934c12008df514ddbbeb06c00",
    (
        "kmer3-logistic",
        "cluster30",
    ): "377eb9234dfa770747064ed48a97c2e622da46076309c61bdf3a4df8fb6578ef",
    (
        "nearest-homolog",
        "random",
    ): "fae5c438350969ff2c21a5ec723df7a17ba1e134b0148cd6e94e33d1798e7daf",
    (
        "nearest-homolog",
        "cluster70",
    ): "fdfae6e018fa5b1f55cc5eb71d3616d8f9795a9164b9af411d91e7b94273ba8b",
    (
        "nearest-homolog",
        "cluster50",
    ): "64ccd1909793305d53cbb85540c6d719caeae5e0c12120e1e2970cd1fcf7b721",
    (
        "nearest-homolog",
        "cluster30",
    ): "fcf894cda818cc1f04b1cb0784563adb0f688c462ece64399f27d5e2ff1d9d9f",
    ("esm2-35m", "random"): "ece6f94926bdac8a12d074c97e2aab3bf9eece623e1eff468ad04d7c5ba06a7d",
    ("esm2-35m", "cluster70"): "a5ea20590c9ad26d2c7d3a06b9e731c1571f47768e69a538600f59a86e14c56e",
    ("esm2-35m", "cluster50"): "4df8ad17f2f19ff7480a5a6ced3c1df0f7d6797c22f125126482307ec8dfe018",
    ("esm2-35m", "cluster30"): "e43fca8fd98f574ac6db7a6bc9a8eee3b928d5eb8d952e9f4c43ba0151cc0736",
    ("esm2-150m", "random"): "0b9c93d4373e1e6b67cc9f84bed6d7506897a0a3ba71443b1998f868f6dd9970",
    ("esm2-150m", "cluster70"): "adea2d4cef3c84688a22cdec5ab3fd2a5b6c799c569c6a2ba800a42c9a1cc26f",
    ("esm2-150m", "cluster50"): "be8e09ad8b049f4de3eeb28fc4d1e17503ac5687109e462fb32f38adf0303493",
    ("esm2-150m", "cluster30"): "eb0e6eaad7790d896ceae6d3cb392811ee719848092c46c15c1eaa8e42e1a253",
}
_NEAREST_HASHES: dict[SplitName, str] = {
    "random": "e3455a777662313a292028f59d8554a94e86c963da4eda7cab155a9dfc804b66",
    "cluster70": "9834cbd5cc6d0dbab37890d0671b531b7015b92ef71075407115b4c89e378bb2",
    "cluster50": "89285603b03972d549d5c6a88fc667fcf5de08453d5f22788284ff8f8d7696d4",
    "cluster30": "d89c37fda9b7f1744d179dcd947763ea0e71a5c7617fa29748dfd949504c4cdd",
}
PUBLIC_ARTIFACTS = (
    "README.md",
    "split_performance_summary.csv",
    "identity_bin_summary.csv",
    "length_bin_summary.csv",
    "class_error_summary.csv",
    "component_size_summary.csv",
    "nearest_homolog_summary.csv",
    "model_comparisons.csv",
    "prediction_agreement.csv",
    "component_influence.csv",
    "robustness_summary.csv",
    "analysis_manifest.json",
    "replay_report.json",
    "figures/macro_f1_by_split.pdf",
    "figures/generalization_gap.pdf",
    "figures/performance_by_identity.pdf",
    "figures/performance_by_length.pdf",
    "figures/per_class_gap.pdf",
    "figures/nearest_homolog_analysis.pdf",
)


class ArtifactIdentity(BaseModel):
    """One immutable project-relative artifact after config path resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    sha256: Sha256


class HistoricalGitArtifact(BaseModel):
    """One immutable artifact read from a released Git object, not current worktree bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: Literal["v0.5.0"]
    path: Literal["uv.lock"]
    sha256: Sha256


class DirectoryIdentity(BaseModel):
    """One directory represented by a canonical recursive file inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    directory_sha256: Sha256


class FormalRunIdentity(DirectoryIdentity):
    """One frozen v0.5 formal session and its sequence-free evidence."""

    access_ledger: ArtifactIdentity
    matrix_summary: ArtifactIdentity
    statistics: ArtifactIdentity


class PredictionArtifact(BaseModel):
    """One canonical v0.5 per-record prediction artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: MethodName
    split: SplitName
    relative_path: str
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("prediction relative_path must be normalized and relative")
        return value


class PredictionInventory(BaseModel):
    """Exact canonical prediction inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_sha256: Sha256
    artifacts: tuple[PredictionArtifact, ...]

    @model_validator(mode="after")
    def require_exact_inventory(self) -> PredictionInventory:
        expected_order = tuple((method, split) for method in METHODS for split in SPLITS)
        observed = tuple((item.method, item.split) for item in self.artifacts)
        if observed != expected_order:
            raise ValueError("prediction inventory must contain the 28 frozen cells in order")
        for item in self.artifacts:
            expected_path = f"v050-test__{item.method}__{item.split}/predictions.parquet"
            if (
                item.relative_path != expected_path
                or item.sha256 != _PREDICTION_HASHES[(item.method, item.split)]
            ):
                raise ValueError("prediction artifact identity differs from the frozen inventory")
        if (
            self.inventory_sha256
            != "0c9522da00914a7086dd251024c0ed714c2a175909d0e2f813465155a4b1174b"
        ):
            raise ValueError("prediction inventory hash differs from the frozen inventory")
        return self


class NearestArtifact(BaseModel):
    """One frozen Nearest Homolog detail table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    split: SplitName
    relative_path: str
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("nearest detail relative_path must be normalized and relative")
        return value


class NearestInventory(BaseModel):
    """Exact four-file Nearest Homolog input inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_sha256: Sha256
    artifacts: tuple[NearestArtifact, ...]

    @model_validator(mode="after")
    def require_exact_inventory(self) -> NearestInventory:
        if tuple(item.split for item in self.artifacts) != SPLITS:
            raise ValueError("nearest-homolog inventory must contain four frozen splits in order")
        for item in self.artifacts:
            expected = f"v050-test__nearest-homolog__{item.split}/nearest_homolog.parquet"
            if item.relative_path != expected or item.sha256 != _NEAREST_HASHES[item.split]:
                raise ValueError("nearest-homolog artifact differs from the frozen inventory")
        if (
            self.inventory_sha256
            != "4d6daba107c51c169d2dce08587887d0f792cc18d0de4e7c1ca345aba3ac0b2d"
        ):
            raise ValueError("nearest-homolog inventory hash differs from the frozen inventory")
        return self


class CohortMetadataIdentity(BaseModel):
    """Sequence-free cohort metadata used only for joins and strata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: Path
    file_sha256: Sha256
    semantic_sha256: Sha256
    content_manifest: Path
    content_manifest_sha256: Sha256
    row_count: Literal[442]
    bootstrap_component_column: Literal["discovery_component_id_cluster30"]


class SplitMetadataIdentity(BaseModel):
    """One frozen split metadata identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SplitName
    manifest: Path
    file_sha256: Sha256
    semantic_sha256: Sha256
    content_manifest: Path
    content_manifest_sha256: Sha256
    train_count: Literal[308]
    validation_count: Literal[68]
    test_count: Literal[66]


class AnalysisInputs(BaseModel):
    """All bytes that may influence a formal v0.6 analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    v050_attestation: ArtifactIdentity
    v050_protocol: ArtifactIdentity
    v050_config: ArtifactIdentity
    v050_lock: HistoricalGitArtifact
    v050_execution_commit: GitCommit
    canonical_prediction_session: Literal["run-a"]
    replay_evidence_session: Literal["run-b"]
    run_a: FormalRunIdentity
    run_b: FormalRunIdentity
    replay_report: ArtifactIdentity
    reviewed_aggregate: DirectoryIdentity
    predictions: PredictionInventory
    nearest_homolog: NearestInventory
    combined_analysis_inventory_sha256: Sha256
    cohort: CohortMetadataIdentity
    splits: tuple[SplitMetadataIdentity, ...]

    @model_validator(mode="after")
    def require_frozen_identities(self) -> AnalysisInputs:
        static = (
            (
                self.v050_attestation.sha256,
                "28d03809b662b9ffd9b3d7e69830b203e1a9390887470dc114c38ef16e0e89c9",
            ),
            (
                self.v050_protocol.sha256,
                "ec2d27d68f373a1f436b56a34022c9527e6a1516831b66b833fc9d1fbbc8fc8c",
            ),
            (
                self.v050_config.sha256,
                "104be8a272c9a0cf2aef1b230c43a4ba70c8dd494d432e24b1ff3859ba2a5e54",
            ),
            (
                self.v050_lock.sha256,
                "95c185c8fe0028e79f2764bc40d5c3e103ecc6969be08f29c97d69e23b991868",
            ),
            (
                self.run_a.directory_sha256,
                "ed39f79cc33248d93ded09a2d379a31427e932f2d710ea1fa1e24df3a941a12c",
            ),
            (
                self.run_b.directory_sha256,
                "39adb11a20ee76ccecc367e699465cdd5a0b58b7eae221661b849e5aa445e286",
            ),
            (
                self.replay_report.sha256,
                "8e7b18f293a0b88bf6ae57d5145fd3f79fb10c3a7e3cfde48c6642894ee785ed",
            ),
            (
                self.reviewed_aggregate.directory_sha256,
                "563b9e829742bfbf9946a874875a171e7bb19fd9848cd66e2d81abf344093791",
            ),
            (
                self.combined_analysis_inventory_sha256,
                "06703d334059d294bfe6d56a636a2ad7a01bb8b0bf82869675029715966b3459",
            ),
        )
        if any(observed != expected for observed, expected in static):
            raise ValueError("v0.5 governing input identity differs from the frozen release")
        if self.v050_execution_commit != "1d9c7e9df54fa3e2d0563f7a00ec94709928250d":
            raise ValueError("v0.5 execution commit differs from the frozen release")
        if tuple(item.name for item in self.splits) != SPLITS:
            raise ValueError("metadata inputs must declare four frozen splits in order")
        return self


class IdentityBin(BaseModel):
    """One fixed nearest-Train identity stratum."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order: int = Field(ge=0)
    id: str
    display: str
    lower: float | None
    upper: float | None
    lower_inclusive: bool
    upper_inclusive: bool
    no_hit: bool


class IntegerBin(BaseModel):
    """One fixed integer-valued stratum."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order: int = Field(ge=0)
    id: str
    display: str
    minimum: int = Field(ge=1)
    maximum: int | None = Field(default=None, ge=1)


class AnalysisStrata(BaseModel):
    """All fixed, result-independent strata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_bins: tuple[IdentityBin, ...]
    length_bins: tuple[IntegerBin, ...]
    component_size_bins: tuple[IntegerBin, ...]

    @model_validator(mode="after")
    def require_fixed_bins(self) -> AnalysisStrata:
        identity = tuple(
            (
                item.order,
                item.id,
                item.lower,
                item.upper,
                item.lower_inclusive,
                item.upper_inclusive,
                item.no_hit,
            )
            for item in self.identity_bins
        )
        if identity != (
            (0, "identity_00_20", 0.0, 0.2, True, False, False),
            (1, "identity_20_30", 0.2, 0.3, True, False, False),
            (2, "identity_30_40", 0.3, 0.4, True, False, False),
            (3, "identity_40_50", 0.4, 0.5, True, False, False),
            (4, "identity_50_70", 0.5, 0.7, True, False, False),
            (5, "identity_70_100", 0.7, 1.0, True, True, False),
            (6, "no_hit", None, None, False, False, True),
        ):
            raise ValueError("identity bins must remain frozen in order")
        length = tuple(
            (item.order, item.id, item.minimum, item.maximum) for item in self.length_bins
        )
        if length != (
            (0, "length_050_199", 50, 199),
            (1, "length_200_399", 200, 399),
            (2, "length_400_599", 400, 599),
            (3, "length_600_799", 600, 799),
            (4, "length_800_1000", 800, 1000),
        ):
            raise ValueError("length bins must remain frozen in order")
        component = tuple(
            (item.order, item.id, item.minimum, item.maximum) for item in self.component_size_bins
        )
        if component != (
            (0, "component_singleton", 1, 1),
            (1, "component_02_04", 2, 4),
            (2, "component_05_09", 5, 9),
            (3, "component_10_19", 10, 19),
            (4, "component_20_plus", 20, None),
        ):
            raise ValueError("component-size bins must remain frozen in order")
        return self


class MethodComparison(BaseModel):
    """One directed within-split method difference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_a: MethodName
    method_b: MethodName
    direction: Literal["method_a_minus_method_b"]


class AnalysisComparisons(BaseModel):
    """Pre-specified RQ5 and RQ6 comparisons."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rq5: tuple[MethodComparison, ...]
    rq6: MethodComparison

    @model_validator(mode="after")
    def require_fixed_pairs(self) -> AnalysisComparisons:
        pairs = tuple((item.method_a, item.method_b) for item in self.rq5)
        if pairs != (
            ("esm2-35m", "aac-logistic"),
            ("esm2-35m", "kmer3-logistic"),
            ("esm2-150m", "aac-logistic"),
            ("esm2-150m", "kmer3-logistic"),
            ("esm2-150m", "esm2-35m"),
        ):
            raise ValueError("RQ5 method comparisons must remain frozen in order")
        if (self.rq6.method_a, self.rq6.method_b) != (
            "esm2-150m",
            "nearest-homolog",
        ):
            raise ValueError("RQ6 method comparison must remain frozen")
        return self


class AnalysisBootstrap(BaseModel):
    """Frozen group-aware percentile interval contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: Literal["cluster30_discovery_component"]
    iterations: Literal[2000]
    confidence_level: float
    interval_method: Literal["percentile"]
    lower_quantile: float
    upper_quantile: float
    quantile_method: Literal["linear"]
    seed: Literal[2026]

    @model_validator(mode="after")
    def require_fixed_interval(self) -> AnalysisBootstrap:
        if (
            self.confidence_level != 0.95
            or self.lower_quantile != 0.025
            or self.upper_quantile != 0.975
        ):
            raise ValueError("analysis bootstrap interval values must remain frozen")
        return self


class AnalysisStatistics(BaseModel):
    """Metrics and resampling identities for confirmatory analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metrics: tuple[MetricName, ...]
    bootstrap: AnalysisBootstrap
    diagnostic_seeds: tuple[int, ...]
    within_split_resampling: Literal["paired_component_bootstrap"]
    cross_split_resampling: Literal["independent_component_bootstrap"]
    generalization_direction: Literal["random_minus_comparison"]
    component_influence_removals: tuple[int, ...]

    @model_validator(mode="after")
    def require_fixed_statistics(self) -> AnalysisStatistics:
        if self.metrics != ("accuracy", "balanced_accuracy", "macro_f1"):
            raise ValueError("analysis metrics must remain frozen in order")
        if self.diagnostic_seeds != (2026, 3407, 42):
            raise ValueError("diagnostic seeds must remain 2026, 3407, 42")
        if self.component_influence_removals != (0, 1, 3, 5):
            raise ValueError("component influence removals must remain 0, 1, 3, 5")
        return self


class ReportingThresholds(BaseModel):
    """Minimum support for metrics and confidence intervals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_sequences_for_metric: Literal[20]
    minimum_components_for_ci: Literal[10]


class PrivacyThresholds(BaseModel):
    """Public small-group suppression thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suppress_groups_below_sequences: Literal[5]
    suppress_groups_below_components: Literal[3]


class AnalysisPermissions(BaseModel):
    """A configuration requests no authority by itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    new_test_inference_authorized: Literal[False]
    frozen_test_output_analysis_authorized: bool

    @field_validator("frozen_test_output_analysis_authorized")
    @classmethod
    def config_cannot_grant_authority(cls, value: bool) -> bool:
        if value:
            raise ValueError("analysis config cannot authorize frozen Test-output access")
        return value


class AnalysisRuntime(BaseModel):
    """Canonical deterministic analysis platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operating_system: Literal["Darwin"]
    architecture: Literal["arm64"]
    python: Literal["3.12"]
    device: Literal["cpu"]
    network_access: Literal[False]
    model_execution: Literal[False]
    source_date_epoch: Literal[0]


class AnalysisOutputs(BaseModel):
    """Fixed private sessions and exact public allowlist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formal_sessions: tuple[str, ...]
    run_a_root: Path
    run_b_root: Path
    replay_report: Path
    aggregate_review_root: Path
    release_root: Path
    public_artifacts: tuple[str, ...]
    refuse_overwrite: Literal[True]

    @model_validator(mode="after")
    def require_fixed_outputs(self) -> AnalysisOutputs:
        if self.formal_sessions != ("analysis-a", "analysis-b"):
            raise ValueError("formal sessions must be exactly analysis-a then analysis-b")
        if self.public_artifacts != PUBLIC_ARTIFACTS:
            raise ValueError("public artifact allowlist must contain exactly 19 frozen files")
        return self


class PostTestAnalysisConfig(BaseModel):
    """Complete Generation-A contract that carries no analysis authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    analysis_type: Literal["frozen_test_output_analysis"]
    name: Literal["v060-post-test-analysis"]
    release_target: Literal["v0.6.0"]
    methods: tuple[MethodName, ...]
    splits: tuple[SplitName, ...]
    label_order: tuple[str, ...]
    inputs: AnalysisInputs
    strata: AnalysisStrata
    comparisons: AnalysisComparisons
    statistics: AnalysisStatistics
    reporting: ReportingThresholds
    privacy: PrivacyThresholds
    permissions: AnalysisPermissions
    runtime: AnalysisRuntime
    outputs: AnalysisOutputs
    attestation: Path

    @model_validator(mode="after")
    def require_complete_frozen_contract(self) -> PostTestAnalysisConfig:
        if self.methods != METHODS:
            raise ValueError("analysis must declare the seven frozen methods in order")
        if self.splits != SPLITS:
            raise ValueError("analysis must declare the four frozen splits in order")
        if self.label_order != LABEL_ORDER:
            raise ValueError("analysis must use the frozen five-label order")
        if not self.attestation.as_posix().endswith(
            "docs/attestations/v0.6.0-analysis-freeze.yaml"
        ):
            raise ValueError("analysis requires the fixed future attestation path")
        return self


__all__ = [
    "LABEL_ORDER",
    "METHODS",
    "PUBLIC_ARTIFACTS",
    "SPLITS",
    "ArtifactIdentity",
    "GitCommit",
    "MethodName",
    "MetricName",
    "PostTestAnalysisConfig",
    "Sha256",
    "SplitName",
]
