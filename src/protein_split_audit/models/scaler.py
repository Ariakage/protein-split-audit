# SPDX-License-Identifier: Apache-2.0

"""Auditable Train-only StandardScaler fitting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes


@dataclass(frozen=True, slots=True)
class ScalerState:
    """Sequence-free identity and fitted values for a Train-only scaler."""

    mean: npt.NDArray[np.float64]
    scale: npt.NDArray[np.float64]
    feature_count: int
    train_count: int
    train_accession_sha256: str
    train_row_index_sha256: str
    embedding_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class FittedTrainScaler:
    """Fitted estimator plus auditable state."""

    estimator: StandardScaler
    state: ScalerState

    def transform(self, matrix: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
        """Transform an aligned dense embedding matrix."""

        return np.asarray(self.estimator.transform(matrix), dtype=np.float64)


def fit_train_scaler(
    matrix: npt.NDArray[np.float32],
    records: Sequence[SequenceRecord],
    *,
    embedding_manifest_sha256: str,
) -> FittedTrainScaler:
    """Fit StandardScaler exclusively on rows marked Train."""

    if matrix.ndim != 2 or matrix.shape[0] != len(records) or matrix.dtype != np.float32:
        raise ValueError("scaler input must be aligned dense float32 embeddings")
    train_indices = [index for index, record in enumerate(records) if record.split == "train"]
    if not train_indices:
        raise ValueError("Train-only scaler requires Train rows")
    estimator = StandardScaler()
    estimator.fit(matrix[train_indices])
    train_accessions = [records[index].accession for index in train_indices]
    state = ScalerState(
        mean=np.asarray(estimator.mean_, dtype=np.float64),
        scale=np.asarray(estimator.scale_, dtype=np.float64),
        feature_count=int(estimator.n_features_in_),
        train_count=len(train_indices),
        train_accession_sha256=sha256_bytes(
            serialize_canonical_json({"train_accessions": train_accessions})
        ),
        train_row_index_sha256=sha256_bytes(
            serialize_canonical_json({"train_row_indices": train_indices})
        ),
        embedding_manifest_sha256=embedding_manifest_sha256,
    )
    return FittedTrainScaler(estimator, state)


__all__ = ["FittedTrainScaler", "ScalerState", "fit_train_scaler"]
