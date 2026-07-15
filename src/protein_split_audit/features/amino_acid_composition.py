# SPDX-License-Identifier: Apache-2.0

"""Fixed-order amino-acid composition features."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from protein_split_audit.features.schemas import ALPHABET
from protein_split_audit.features.validation import SequenceRecord


def extract_aac(records: Sequence[SequenceRecord]) -> npt.NDArray[np.float64]:
    """Return 20 relative amino-acid frequencies per sequence."""

    matrix = np.empty((len(records), len(ALPHABET)), dtype=np.float64)
    for row_index, record in enumerate(records):
        length = len(record.sequence)
        if length == 0:
            raise ValueError("AAC cannot represent an empty sequence")
        matrix[row_index] = [record.sequence.count(amino_acid) / length for amino_acid in ALPHABET]
    return matrix


__all__ = ["extract_aac"]
