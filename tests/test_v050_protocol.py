# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import yaml

from protein_split_audit.provenance import sha256_file

PROJECT_ROOT = Path(__file__).parents[1]
PROTOCOL = PROJECT_ROOT / "docs/protocols/v0.5.0-frozen-test-evaluation.md"
CONFIG = PROJECT_ROOT / "configs/experiment/v050-test.yaml"


def test_v050_protocol_records_the_resolved_maintainer_decisions() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")

    required = (
        "real_test_access_authorized: false",
        "seven methods and four split strategies, or 28 Test cells",
        "Cluster30 discovery component",
        "iterations: 2000",
        "interval_method: percentile",
        "lower_quantile: 0.025",
        "upper_quantile: 0.975",
        "seed: 2026",
        "test_access_started_at_utc",
        "Run A and Replay B",
        "confusion_matrices.csv",
        "700 rows",
        "GitHub Draft Release",
        "SHA256SUMS",
        "protein-split-audit 0.4.0 -> 0.5.0",
    )
    for value in required:
        assert value in text

    upper = text.upper()
    assert "TBD" not in upper
    assert "TODO" not in upper
    assert "PLACEHOLDER" not in upper


def test_v050_config_binds_all_known_upstream_hashes() -> None:
    mapping = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(mapping, dict)

    expected = {
        "docs/protocols/v0.3.0-classical-baselines.md": (
            "9be55bf958fade7f2f88c501429521693c9f2be32aab68cede257216ca7fe27a"
        ),
        "docs/attestations/v0.3.0-protocol-freeze.yaml": (
            "a1b1918a07a24d3fb7d46aa8eada9e823b25526d44997f2cc7a72526a71a55b2"
        ),
        "docs/protocols/v0.4.0-esm2-baselines.md": (
            "b23329c1d76558d30e80dba6563525624f00d14a1fe22a75baaca23ffc504694"
        ),
        "docs/attestations/v0.4.0-protocol-freeze.yaml": (
            "ddeed606f308363a457e3edf0646275f788eae657778de03c86c3eed9bb214f7"
        ),
        "configs/feature/length.yaml": (
            "f84c0b09ac503d43df8f4a39e174fcef7c52088d639268cf47da318ed3dbd37e"
        ),
        "configs/feature/aac.yaml": (
            "db09777a78b0e23421f0bfd02d21c8091e9e9690faa34975faf4615977113e8b"
        ),
        "configs/feature/kmer3.yaml": (
            "470b9158c547c6d14ad09f391ad9f059dc9ef1d34767f047a99257e394e98381"
        ),
        "configs/model/majority.yaml": (
            "26ce757fba41279d760455dde4341ba5daa15c4235a5ec90723fa980c96e245b"
        ),
        "configs/model/logistic_regression.yaml": (
            "009e3cb150c3df47b4da298609ca176bbc7bf6142574ec10f05c3aca55f8f027"
        ),
        "configs/model/nearest_homolog.yaml": (
            "d3ac74c7af0df6e51d272ad50f1e8ad83731ab5ee890b73b9ff523ef53a2ddba"
        ),
        "configs/embedding/esm2_35m.yaml": (
            "c0634997b3048c1474876d6a8f5db7c049746385c4a5ed3a2d84e6ae3a75449c"
        ),
        "configs/embedding/esm2_150m.yaml": (
            "4ab75418b6a6c46ca37a203c5c6475ed429eecda3fa6068406bbb432b6880d0a"
        ),
        "configs/model/esm_linear_probe.yaml": (
            "12b9aeb2732de404275bc728adb93f34daa7075c8f1e3afa1db684099ff61eb1"
        ),
        "configs/experiment/v030-validation.yaml": (
            "0191ddd65fb5827e473f5048328438fab5c7a0c054f188543d46a6495a90ffd4"
        ),
        "configs/experiment/v040-validation.yaml": (
            "e0776cdad32f43e41695166dfebe5e0545ead11d4abe7ee5d4dfb13546ac1a44"
        ),
        "results/released/v0.3.0/validation_summary.csv": (
            "73ee1c4f8c454a8570058224c9257d4f924eac8c8681fcb78991d99fa6612dc2"
        ),
        "results/released/v0.3.0/validation_per_class.csv": (
            "a70dbfa155d8589530697c30b0a33da1a205e2ffc2fd083e72ffb1b5fa2ad667"
        ),
        "results/released/v0.4.0/esm_validation_summary.csv": (
            "2e96c04dc18695649ad51cf1fe9ee5b7a9c41fe4974a71d6e652b7d3ef4f5b6f"
        ),
        "results/released/v0.4.0/esm_validation_per_class.csv": (
            "8af608fd622acc2634b82c677f1f51c9aff63c5ae7977b4ab738d0ba14faa7f9"
        ),
        "results/released/v0.4.0/classical_vs_esm_summary.csv": (
            "d73af232cf5dedb675fff931391c35aa326d0e526a42a0bbb83d1d7e45fa894c"
        ),
        "results/released/v0.4.0/environment_summary.json": (
            "1ab0412f055c5b375bd4c5931e5b2276fcd859c3cc31b4cfcf227935cf4bee15"
        ),
    }
    frozen = mapping["tracked_evidence"]
    assert isinstance(frozen, list)
    configured = {
        (CONFIG.parent / entry["path"]).resolve().relative_to(PROJECT_ROOT).as_posix(): entry[
            "sha256"
        ]
        for entry in frozen
    }
    assert configured == expected
    for relative, digest in expected.items():
        assert sha256_file(PROJECT_ROOT / relative) == digest
