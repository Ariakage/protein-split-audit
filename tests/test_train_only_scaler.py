# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import numpy as np

from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.scaler import fit_train_scaler


def _record(accession: str, split: str) -> SequenceRecord:
    return SequenceRecord(accession, b"a" * 32, "1.1", split, "A" * 50)


def test_scaler_fits_train_rows_only_and_binds_training_identity() -> None:
    records = (_record("T0", "train"), _record("T1", "train"), _record("V0", "validation"))
    matrix = np.asarray([[1.0, 10.0], [3.0, 14.0], [10000.0, -10000.0]], dtype=np.float32)

    fitted = fit_train_scaler(matrix, records, embedding_manifest_sha256="1" * 64)

    np.testing.assert_array_equal(fitted.state.mean, np.asarray([2.0, 12.0]))
    np.testing.assert_array_equal(fitted.state.scale, np.asarray([1.0, 2.0]))
    assert fitted.state.train_count == 2
    assert fitted.state.train_accession_sha256 == (
        "f86a4804369ecebaa40f8976e80230a408ea0e6f8fed7cecca5f66c652c9dd7f"
    )
    assert fitted.state.embedding_manifest_sha256 == "1" * 64
