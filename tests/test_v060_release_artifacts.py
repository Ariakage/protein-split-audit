# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from protein_split_audit.analysis.privacy import validate_v060_release_bundle
from protein_split_audit.analysis.schemas import PUBLIC_ARTIFACTS
from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
RELEASE_ROOT = PROJECT_ROOT / "results/released/v0.6.0"
EXPECTED_RELEASE_HASHES = {
    "README.md": "aa720c92056871383fdd8c8712da1c2d78b6d12bde96487e692c49d8bf54d7f9",
    "analysis_manifest.json": ("50e86a51bfe25aaf61cee457563ce3eff130427675877100908d8c2432e25d0f"),
    "class_error_summary.csv": ("bac65df51e38cb7c583c936c5fbc437365e220ba145139c78a9b7273e832a026"),
    "component_influence.csv": ("1848584cf7078ebc88782a9e7b7a061b3d7e415785b85a0b2ea611085cd9104a"),
    "component_size_summary.csv": (
        "85dffd3cfd2575e7ddf6bd329c4fc38bba35f24e0ed27d9cb5c98259cf08dfc6"
    ),
    "figures/generalization_gap.pdf": (
        "04657f6fcbbabae7e76a1dce0497bb96f6dc2e8fc412d5ef5810c88b2d9c3e30"
    ),
    "figures/macro_f1_by_split.pdf": (
        "44ee3eb17b80de53e3d9c84f0af992b083a65f7060223e5ec8fcbe87f92ccfbc"
    ),
    "figures/nearest_homolog_analysis.pdf": (
        "146ef2b6ad3a58e4b469981ce83ec22e578d88bb82855f74071a045425702483"
    ),
    "figures/per_class_gap.pdf": (
        "896f9aef8b1b33b5192d09f66663d79714e5cf93cedb0232b7a00313dbcab2b8"
    ),
    "figures/performance_by_identity.pdf": (
        "3276d3c2e73352472d13e04e4dbff1d5d357e00a3975762e38442da47ed10f7b"
    ),
    "figures/performance_by_length.pdf": (
        "cc1d51cdc003beb05542dc826a6d0c1207bb4984ed220c6afecf36e00794ca07"
    ),
    "identity_bin_summary.csv": (
        "d627e02b78a51fb92f84fe7c6781178c69706980d499f4eb5cda486235eb6ff9"
    ),
    "length_bin_summary.csv": ("2df7e90f04e86409abd2b7df47c8a63be69151d0728dd67c8bcbf9ab05c2f5ac"),
    "model_comparisons.csv": ("864a6ca87ab3583687b9474fa8f298e0ec96e97d9977267c1cf421150a14ead3"),
    "nearest_homolog_summary.csv": (
        "1af61bbef9342238a4456a9703082543499f20a8b817ad769e30d71061114482"
    ),
    "prediction_agreement.csv": (
        "cf21244356f13ffd542a3649af860cbde20ea4a4797140e8a0f22e6f85a3fb9f"
    ),
    "replay_report.json": ("447cc115f469fb3cc0d6a1f78ffbb9219eada8cbefb548f039a465775b53bdf9"),
    "robustness_summary.csv": ("77907241c597f2de4702316e809ff849bed50dadf62a62ef538af790e2843557"),
    "split_performance_summary.csv": (
        "b23134b2a5b11ec899ee7b906a6064d7310fdfa0d513244668a324afee55a7a3"
    ),
}


def test_release_c_contains_exactly_the_owner_approved_bundle() -> None:
    observed = {
        path.relative_to(RELEASE_ROOT).as_posix(): sha256_file(path)
        for path in RELEASE_ROOT.rglob("*")
        if path.is_file()
    }

    assert set(EXPECTED_RELEASE_HASHES) == set(PUBLIC_ARTIFACTS)
    assert observed == EXPECTED_RELEASE_HASHES
    validate_v060_release_bundle(RELEASE_ROOT)


def test_release_c_records_execution_and_presentation_approvals() -> None:
    notes = (PROJECT_ROOT / "docs/releases/v0.6.0.md").read_text(encoding="utf-8")

    assert "73febd1be2a18d3c9b54f7aacf5cd90a208fbd52" in notes
    assert "56cc94eeebb7d2c649dab8fd7b04ac0242b25abe" in notes
    assert "issuecomment-5010435346" in notes
    assert "issuecomment-5010597548" in notes
    assert "No additional Test access" in notes
    assert "not a general benchmark" in notes
