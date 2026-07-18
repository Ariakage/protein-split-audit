# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_split_audit.analysis.authorization as authorization_module
import protein_split_audit.config as config_module
import protein_split_audit.paths as paths_module
from protein_split_audit.analysis.aggregate import (
    csv_bytes,
    json_bytes,
    run_post_test_analysis,
    write_deterministic_bundle,
)


def test_csv_and_json_serialization_are_canonical() -> None:
    csv = csv_bytes(
        ("order", "estimate", "missing", "label"),
        ((0, -0.0, None, "2.7"), (1, 0.125, None, "3.1")),
    )
    assert csv == (b"order,estimate,missing,label\n0,0,NA,2.7\n1,0.125,NA,3.1\n")
    assert json_bytes({"z": 1, "a": -0.0}) == b'{\n  "a": 0.0,\n  "z": 1\n}\n'


def test_bundle_writer_refuses_overwrite_and_returns_hashes(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    outputs = {"one.csv": b"a\n1\n", "manifest.json": b"{}\n"}
    result = write_deterministic_bundle(destination, outputs)

    assert tuple(result.file_sha256) == ("manifest.json", "one.csv")
    assert (destination / "one.csv").read_bytes() == b"a\n1\n"
    with pytest.raises(FileExistsError, match="overwrite"):
        write_deterministic_bundle(destination, outputs)


@pytest.mark.parametrize(
    "session,output_name",
    (
        ("analysis-r1-a", "v0.6.0-analysis-r1-a"),
        ("analysis-r1-b", "v0.6.0-analysis-r1-b"),
    ),
)
def test_formal_runner_maps_each_r1_session_to_its_frozen_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session: str,
    output_name: str,
) -> None:
    run_a = tmp_path / "v0.6.0-analysis-r1-a"
    run_b = tmp_path / "v0.6.0-analysis-r1-b"
    config = SimpleNamespace(
        outputs=SimpleNamespace(
            formal_sessions=("analysis-r1-a", "analysis-r1-b"),
            run_a_root=run_a,
            run_b_root=run_b,
        )
    )

    class ReachedAuthorizationGate(Exception):
        pass

    monkeypatch.setattr(paths_module, "find_project_root", lambda _: tmp_path)
    monkeypatch.setattr(config_module, "load_analysis_config", lambda _: config)
    monkeypatch.setattr(
        authorization_module,
        "verify_analysis_authorization",
        lambda *_: (_ for _ in ()).throw(ReachedAuthorizationGate),
    )

    with pytest.raises(ReachedAuthorizationGate):
        run_post_test_analysis(
            tmp_path / "config.yaml",
            tmp_path / "attestation.yaml",
            session,
            tmp_path / output_name,
        )
