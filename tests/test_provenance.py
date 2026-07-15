# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import subprocess
from decimal import Decimal
from pathlib import Path

import protein_split_audit.provenance as provenance_module
from protein_split_audit.provenance import git_metadata, sha256_bytes, sha256_file


def test_sha256_helpers_match_hashlib(tmp_path: Path) -> None:
    payload = b"ProteinSplitAudit\n"
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    assert sha256_bytes(payload) == expected
    assert sha256_file(source) == expected


def test_serialize_canonical_json_is_compact_sorted_utf8_with_fixed_decimals() -> None:
    serializer = getattr(provenance_module, "serialize_canonical_json", None)

    assert callable(serializer), "serialize_canonical_json must be public"
    payload = serializer(
        {
            "z_decimal": Decimal("1.2300"),
            "unicode": "酶",
            "nested": {"nullable": None, "enabled": True},
            "float": 7.5,
        }
    )

    assert (
        payload
        == (
            '{"float":"7.5","nested":{"enabled":true,"nullable":null},'
            '"unicode":"酶","z_decimal":"1.2300"}\n'
        ).encode()
    )


def test_git_metadata_reports_non_repository(tmp_path: Path) -> None:
    metadata = git_metadata(tmp_path)

    assert metadata.available is False
    assert metadata.commit is None
    assert metadata.dirty is None


def test_git_metadata_tracks_uncommitted_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)

    clean = git_metadata(tmp_path)
    (tmp_path / "untracked.txt").write_text("change\n", encoding="utf-8")
    dirty = git_metadata(tmp_path)

    assert clean.available is True
    assert clean.commit is None
    assert clean.dirty is False
    assert dirty.available is True
    assert dirty.dirty is True
