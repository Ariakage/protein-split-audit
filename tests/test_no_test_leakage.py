# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest


def test_real_test_gate_denies_before_opening_inputs(tmp_path: Path) -> None:
    from protein_split_audit.experiments.test_gate import RealTestAccessDenied, enforce_test_gate

    attestation = tmp_path / "attestation.yaml"
    attestation.write_text(
        """\
schema_version: 1
project: ProteinSplitAudit
release_target: v0.3.0
attestation_type: protocol_freeze
experiment:
  evaluation_split: validation
  real_test_access_authorized: false
""",
        encoding="utf-8",
    )
    opened = False

    def forbidden_open() -> None:
        nonlocal opened
        opened = True

    with pytest.raises(RealTestAccessDenied, match="Real test access is not authorized"):
        enforce_test_gate(attestation, before_real_input=forbidden_open)
    assert opened is False
