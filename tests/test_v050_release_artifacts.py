# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from protein_split_audit.evaluation.test_aggregate import write_test_aggregates
from protein_split_audit.experiments.replay import compare_test_replays
from protein_split_audit.provenance import sha256_file
from protein_split_audit.publication import (
    SANITIZED_TEST_FILENAMES,
    validate_sanitized_test_bundle,
)
from tests.test_test_replay import _formal_pair
from tests.v050_aggregate_helpers import enrich_formal_pair

PROJECT_ROOT = Path(__file__).parents[1]
EXPECTED_RELEASE_HASHES = {
    "README.md": "7b75f8d1d00ce8a172dbcf2610148a115854d9c92b3e9c77f97c05bedf057382",
    "confidence_intervals.csv": (
        "07d33e1c84a88446dfcd7b979251ba303d4ba823b31b11ce666aae65831e3455"
    ),
    "confusion_matrices.csv": ("8858129ac28706500d6783e7f1e0c3ad0b557ce36117eedfb51c7319c3748197"),
    "environment_summary.json": (
        "c2d2c79ece65ef10eae81806b085f0e36f51cf222a529856c47cd266883de346"
    ),
    "generalization_gap.csv": ("4ddd2f65461ca8ad5d45812c4ae8f70af32b3fbf26d22e9899f5269aa5648dd8"),
    "input_hashes.json": ("40696ef2c224ab60fd8f8cae12d4e95f9cb9e456f30d532ac22a29140727d8c4"),
    "method_comparisons.csv": ("2a9782adf3b424a0e83bc139ebb0b477489b10da372dcf94192d55591a335f5f"),
    "nearest_homolog_summary.csv": (
        "472a94945023b310a793bf1300e3ed762343fde6bb1bd40382e4afbd2a03fa41"
    ),
    "protocol_attestation.yaml": (
        "28d03809b662b9ffd9b3d7e69830b203e1a9390887470dc114c38ef16e0e89c9"
    ),
    "replay_report.json": ("8e7b18f293a0b88bf6ae57d5145fd3f79fb10c3a7e3cfde48c6642894ee785ed"),
    "test_per_class.csv": ("cbcfb974f1f91765ff5a734475faded93067e4c4a40f884d553c9b86aa0dd201"),
    "test_summary.csv": ("e4a9006162ff2bae6d4afaf4d9ca85fb5c97daf888ef2d043ad365f2ba8dce41"),
}


def test_aggregate_has_exact_public_file_set_and_rehashes_replay_roots(
    tmp_path: Path,
) -> None:
    attestation = tmp_path / "attestation.yaml"
    attestation.write_text("schema_version: 1\n", encoding="utf-8")
    first, second = _formal_pair(
        tmp_path,
        attestation_sha256=sha256_file(attestation),
    )
    enrich_formal_pair(first, second)
    replay = compare_test_replays(first, second, tmp_path / "replay.json")
    assert replay.capability is not None
    output = tmp_path / "aggregate"
    result = write_test_aggregates(
        replay.capability,
        output,
        config_path=PROJECT_ROOT / "configs/experiment/v050-test.yaml",
        attestation_path=attestation,
    )

    assert {path.name for path in result.files} == SANITIZED_TEST_FILENAMES
    assert {path.name for path in output.iterdir()} == SANITIZED_TEST_FILENAMES

    (first / "statistics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after verification"):
        write_test_aggregates(
            replay.capability,
            tmp_path / "second-aggregate",
            config_path=PROJECT_ROOT / "configs/experiment/v050-test.yaml",
            attestation_path=attestation,
        )


def test_release_c_contains_the_exact_reviewed_aggregate_bytes() -> None:
    release_root = PROJECT_ROOT / "results/released/v0.5.0"
    outputs = {path: path.read_bytes() for path in sorted(release_root.iterdir()) if path.is_file()}

    assert {path.name for path in outputs} == SANITIZED_TEST_FILENAMES
    assert set(EXPECTED_RELEASE_HASHES) == SANITIZED_TEST_FILENAMES
    for path in outputs:
        assert sha256_file(path) == EXPECTED_RELEASE_HASHES[path.name]
    validate_sanitized_test_bundle(outputs)

    attestation = PROJECT_ROOT / "docs/attestations/v0.5.0-test-freeze-r1.yaml"
    assert (release_root / "protocol_attestation.yaml").read_bytes() == attestation.read_bytes()


def test_release_c_records_both_permanent_review_comments() -> None:
    notes = (PROJECT_ROOT / "docs/releases/v0.5.0.md").read_text(encoding="utf-8")

    assert "issuecomment-5009657104" in notes
    assert "issuecomment-5009767954" in notes
    assert "controlled Test pilot" in notes
    assert "third Test session" in notes
