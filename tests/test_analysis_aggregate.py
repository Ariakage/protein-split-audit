# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from protein_split_audit.analysis.aggregate import (
    csv_bytes,
    json_bytes,
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
