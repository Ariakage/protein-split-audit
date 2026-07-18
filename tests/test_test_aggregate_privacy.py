# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from protein_split_audit.publication import (
    SANITIZED_TEST_FILENAMES,
    PublicationError,
    validate_sanitized_test_bundle,
)


def _empty_bundle(root: Path) -> dict[Path, bytes]:
    outputs = {root / name: b"safe\n" for name in SANITIZED_TEST_FILENAMES}
    for path in tuple(outputs):
        if path.suffix == ".json":
            outputs[path] = b"{}\n"
        elif path.suffix == ".csv":
            outputs[path] = b"safe_column\n"
        elif path.suffix == ".yaml":
            outputs[path] = b"schema_version: 1\n"
    return outputs


@pytest.mark.parametrize(
    "payload",
    (
        b"private_path: /Users/example/private\n",
        b"accession,value\nP0001,1\n",
        b"sequence\n" + b"A" * 60 + b"\n",
        b"Authorization: Bearer secret-token-value\n",
        b"SYNTHETIC_SECRET_CANARY\n",
    ),
)
def test_public_bundle_privacy_scan_fails_closed(tmp_path: Path, payload: bytes) -> None:
    outputs = _empty_bundle(tmp_path)
    outputs[tmp_path / "README.md"] = payload

    with pytest.raises(PublicationError, match=r"privacy|forbidden"):
        validate_sanitized_test_bundle(outputs)
