# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import io
import subprocess
from pathlib import Path

from protein_split_audit.publication import (
    SANITIZED_TEST_FILENAMES,
    validate_sanitized_test_bundle,
)

PROJECT_ROOT = Path(__file__).parents[1]
RELEASE_ROOT = PROJECT_ROOT / "results/released/v0.5.0"


def test_v050_release_bundle_passes_the_publication_privacy_gate() -> None:
    outputs = {path: path.read_bytes() for path in sorted(RELEASE_ROOT.iterdir()) if path.is_file()}

    validate_sanitized_test_bundle(outputs)


def test_v050_release_tracks_only_the_approved_aggregate_file_set() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "results/released/v0.5.0"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = {Path(line).name for line in completed.stdout.splitlines() if line}

    assert tracked == SANITIZED_TEST_FILENAMES


def test_v050_confusion_table_is_aggregate_and_complete() -> None:
    content = (RELEASE_ROOT / "confusion_matrices.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(content)))

    assert len(rows) == 700
    assert tuple(rows[0]) == (
        "method",
        "split",
        "true_label",
        "predicted_label",
        "count",
        "row_fraction",
    )
    assert all(set(row) == set(rows[0]) for row in rows)
