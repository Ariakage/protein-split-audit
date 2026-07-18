# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from protein_split_audit.analysis.aggregate import CSV_SCHEMAS
from protein_split_audit.analysis.privacy import (
    AnalysisPrivacyError,
    validate_v060_release_bundle,
)
from protein_split_audit.analysis.schemas import PUBLIC_ARTIFACTS


def _bundle(root: Path) -> None:
    for name in PUBLIC_ARTIFACTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name in CSV_SCHEMAS:
            path.write_text(",".join(CSV_SCHEMAS[name]) + "\n", encoding="utf-8")
        elif name.endswith(".json"):
            path.write_text('{"schema_version":1}\n', encoding="utf-8")
        elif name.endswith(".pdf"):
            path.write_bytes(b"%PDF-1.4\n% deterministic synthetic fixture\n%%EOF\n")
        else:
            path.write_text("# ProteinSplitAudit v0.6.0 aggregate\n", encoding="utf-8")


def test_privacy_scanner_accepts_only_exact_allowlist(tmp_path: Path) -> None:
    _bundle(tmp_path)
    validate_v060_release_bundle(tmp_path)
    (tmp_path / "extra.csv").write_text("x\n", encoding="utf-8")
    with pytest.raises(AnalysisPrivacyError, match="allowlist"):
        validate_v060_release_bundle(tmp_path)


@pytest.mark.parametrize(
    "canary",
    (
        "P12345",
        "/Users/private/project",
        "ACDEFGHIKLMNPQRSTVWY" * 3,
        "Authorization: Bearer secret-token-value",
        "a" * 64,
    ),
)
def test_privacy_scanner_rejects_identity_path_sequence_secret_and_hash(
    tmp_path: Path,
    canary: str,
) -> None:
    _bundle(tmp_path)
    (tmp_path / "README.md").write_text(canary + "\n", encoding="utf-8")
    with pytest.raises(AnalysisPrivacyError, match="privacy"):
        validate_v060_release_bundle(tmp_path)


def test_privacy_scanner_rejects_exact_metric_in_suppressed_row(tmp_path: Path) -> None:
    _bundle(tmp_path)
    name = "identity_bin_summary.csv"
    columns = CSV_SCHEMAS[name]
    row = {column: "NA" for column in columns}
    row.update(
        {
            "schema_version": "1",
            "reporting_status": "privacy_suppressed",
            "sequence_count_display": "<5",
            "component_count_display": "<3",
            "estimate": "0.5",
        }
    )
    (tmp_path / name).write_text(
        ",".join(columns) + "\n" + ",".join(row[column] for column in columns) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AnalysisPrivacyError, match="suppressed"):
        validate_v060_release_bundle(tmp_path)
