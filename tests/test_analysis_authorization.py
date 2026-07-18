# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from protein_split_audit.analysis.authorization import (
    AnalysisFreezeAttestation,
    AnalysisOutputAccessDenied,
    require_verified_analysis_authorization,
    verify_analysis_authorization,
)
from protein_split_audit.config import load_analysis_config
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
CONFIG = PROJECT_ROOT / "configs/analysis/v060-post-test-analysis.yaml"


def _mapping() -> dict[str, object]:
    digest = "a" * 64
    commit = "b" * 40
    config = load_analysis_config(CONFIG)
    return {
        "schema_version": 1,
        "project": "ProteinSplitAudit",
        "release_target": "v0.6.0",
        "attestation_type": "frozen_test_output_analysis",
        "protocol": {
            "path": "docs/protocols/v0.6.0-post-test-analysis.md",
            "sha256": digest,
        },
        "code": {
            "generation_git_commit": commit,
            "generation_git_dirty": False,
            "software_version": "0.6.0",
            "python_version": "3.12.11",
            "configuration": {
                "path": "configs/analysis/v060-post-test-analysis.yaml",
                "sha256": digest,
            },
            "uv_lock": {"path": "uv.lock", "sha256": digest},
            "dependency_diff": {
                "path": "docs/audits/v0.6.0-dependency-diff.md",
                "sha256": digest,
            },
        },
        "frozen_inputs": {
            "v050_attestation_sha256": config.inputs.v050_attestation.sha256,
            "v050_replay_sha256": config.inputs.replay_report.sha256,
            "run_a_directory_sha256": config.inputs.run_a.directory_sha256,
            "run_b_directory_sha256": config.inputs.run_b.directory_sha256,
            "prediction_inventory_sha256": config.inputs.predictions.inventory_sha256,
            "nearest_homolog_inventory_sha256": config.inputs.nearest_homolog.inventory_sha256,
            "combined_analysis_inventory_sha256": (
                config.inputs.combined_analysis_inventory_sha256
            ),
            "cohort_file_sha256": config.inputs.cohort.file_sha256,
            "split_file_sha256": {item.name: item.file_sha256 for item in config.inputs.splits},
            "canonical_prediction_session": "run-a",
            "replay_evidence_session": "run-b",
        },
        "permissions": {
            "new_test_inference_authorized": False,
            "frozen_test_output_analysis_authorized": True,
        },
        "analysis": {
            "methods": list(config.methods),
            "splits": list(config.splits),
            "label_order": list(config.label_order),
            "formal_sessions": ["analysis-a", "analysis-b"],
        },
        "strata": config.strata.model_dump(mode="json"),
        "comparisons": config.comparisons.model_dump(mode="json"),
        "statistics": config.statistics.model_dump(mode="json"),
        "reporting": config.reporting.model_dump(mode="json"),
        "privacy": config.privacy.model_dump(mode="json"),
        "publication": {
            "public_artifacts": list(config.outputs.public_artifacts),
            "refuse_overwrite": True,
        },
        "runtime": {
            "operating_system": "Darwin",
            "architecture": "arm64",
            "python": "3.12",
            "device": "cpu",
            "network_access": False,
            "model_execution": False,
        },
        "approval": {
            "approved_by": "Ariakage",
            "approved_at_utc": "2026-07-18T08:00:00Z",
            "approval_reference": (
                "https://github.com/Ariakage/protein-split-audit/pull/5#issuecomment-5010000000"
            ),
            "author_association": "OWNER",
            "approval_comment_sha256": digest,
        },
    }


def test_analysis_attestation_requires_the_narrow_authority() -> None:
    attestation = AnalysisFreezeAttestation.model_validate(_mapping())

    assert attestation.permissions.new_test_inference_authorized is False
    assert attestation.permissions.frozen_test_output_analysis_authorized is True
    assert attestation.analysis.formal_sessions == ("analysis-a", "analysis-b")


@pytest.mark.parametrize(
    "mutation, message",
    (
        (
            lambda value: value["permissions"].__setitem__("new_test_inference_authorized", True),
            "Input should be False",
        ),
        (
            lambda value: value["permissions"].__setitem__(
                "frozen_test_output_analysis_authorized", False
            ),
            "Input should be True",
        ),
        (
            lambda value: value["analysis"].__setitem__("formal_sessions", ["analysis-a"]),
            "formal sessions",
        ),
        (
            lambda value: value["approval"].__setitem__(
                "approval_reference", "https://example.test/approval"
            ),
            "permanent GitHub",
        ),
        (lambda value: value.__setitem__("extra", True), "Extra inputs"),
    ),
)
def test_analysis_attestation_rejects_wider_or_incomplete_authority(
    mutation: object,
    message: str,
) -> None:
    mapping = deepcopy(_mapping())
    assert callable(mutation)
    mutation(mapping)

    with pytest.raises(ValidationError, match=message):
        AnalysisFreezeAttestation.model_validate(mapping)


def test_unverified_values_cannot_open_frozen_outputs() -> None:
    with pytest.raises(AnalysisOutputAccessDenied, match="not authorized"):
        require_verified_analysis_authorization(object())


def test_verifier_issues_capability_only_after_metadata_and_input_gates(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "configs/analysis").mkdir(parents=True)
    (root / "docs/protocols").mkdir(parents=True)
    (root / "docs/audits").mkdir(parents=True)
    (root / "docs/attestations").mkdir(parents=True)
    config_path = root / "configs/analysis/v060-post-test-analysis.yaml"
    config_path.write_bytes(CONFIG.read_bytes())
    protocol = root / "docs/protocols/v0.6.0-post-test-analysis.md"
    protocol.write_text("protocol\n", encoding="utf-8")
    lock = root / "uv.lock"
    lock.write_text("lock\n", encoding="utf-8")
    dependency = root / "docs/audits/v0.6.0-dependency-diff.md"
    dependency.write_text("audit\n", encoding="utf-8")

    mapping = _mapping()
    code = mapping["code"]
    assert isinstance(code, dict)
    code["configuration"]["sha256"] = sha256_file(config_path)
    code["uv_lock"]["sha256"] = sha256_file(lock)
    code["dependency_diff"]["sha256"] = sha256_file(dependency)
    mapping["protocol"]["sha256"] = sha256_file(protocol)
    attestation_path = root / "docs/attestations/v0.6.0-analysis-freeze.yaml"
    attestation_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")

    events: list[str] = []
    authorization = verify_analysis_authorization(
        config_path,
        attestation_path,
        root,
        observed_software_version="0.6.0",
        observed_python_version="3.12.11",
        git_verifier=lambda *_: events.append("git") or "c" * 40,
        frozen_input_verifier=lambda _: events.append("inputs"),
    )

    require_verified_analysis_authorization(authorization)
    assert events == ["git", "inputs"]
    assert authorization.canonical_prediction_session == "run-a"
    assert authorization.execution_commit == "c" * 40


def test_verifier_fails_closed_before_input_gate_on_bad_metadata(tmp_path: Path) -> None:
    root = tmp_path / "project"
    config_path = root / "configs/analysis/v060-post-test-analysis.yaml"
    attestation_path = root / "docs/attestations/v0.6.0-analysis-freeze.yaml"
    config_path.parent.mkdir(parents=True)
    attestation_path.parent.mkdir(parents=True)
    config_path.write_bytes(CONFIG.read_bytes())
    mapping = _mapping()
    mapping["approval"]["approval_comment_sha256"] = "bad"
    attestation_path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    called = False

    def inputs(_: object) -> None:
        nonlocal called
        called = True

    with pytest.raises(AnalysisOutputAccessDenied, match="not authorized"):
        verify_analysis_authorization(
            config_path,
            attestation_path,
            root,
            observed_software_version="0.6.0",
            observed_python_version="3.12.11",
            git_verifier=lambda *_: "c" * 40,
            frozen_input_verifier=inputs,
        )
    assert called is False
