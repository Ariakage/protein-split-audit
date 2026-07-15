# SPDX-License-Identifier: Apache-2.0

"""Fixed complete 3-mer relative-frequency CSR features."""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Sequence

import numpy as np
from scipy import sparse  # type: ignore[import-untyped]

from protein_split_audit.features.schemas import ALPHABET
from protein_split_audit.features.validation import SequenceRecord

KMER3_VOCABULARY = tuple(
    "".join(characters) for characters in itertools.product(ALPHABET, repeat=3)
)
KMER3_INDEX = {kmer: index for index, kmer in enumerate(KMER3_VOCABULARY)}


def extract_kmer3(records: Sequence[SequenceRecord]) -> sparse.csr_matrix:
    """Return fixed-order overlapping 3-mer relative frequencies."""

    row_indices: list[int] = []
    column_indices: list[int] = []
    values: list[float] = []
    for row_index, record in enumerate(records):
        window_count = len(record.sequence) - 2
        if window_count <= 0:
            raise ValueError(f"sequence is shorter than k=3: {record.accession}")
        counts = Counter(record.sequence[index : index + 3] for index in range(window_count))
        for kmer in sorted(counts, key=KMER3_INDEX.__getitem__):
            column = KMER3_INDEX.get(kmer)
            if column is None:
                raise ValueError(f"sequence contains a non-protocol 3-mer: {record.accession}")
            row_indices.append(row_index)
            column_indices.append(column)
            values.append(counts[kmer] / window_count)
    matrix = sparse.csr_matrix(
        (np.asarray(values, dtype=np.float64), (row_indices, column_indices)),
        shape=(len(records), len(KMER3_VOCABULARY)),
        dtype=np.float64,
    )
    matrix.sort_indices()
    return matrix


__all__ = ["KMER3_INDEX", "KMER3_VOCABULARY", "extract_kmer3"]
