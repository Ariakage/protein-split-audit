# SPDX-License-Identifier: Apache-2.0

"""Sequence-length feature extraction."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from protein_split_audit.features.validation import SequenceRecord


def extract_length(records: Sequence[SequenceRecord]) -> npt.NDArray[np.float64]:
    """Return one float64 sequence-length column in input row order."""

    return np.asarray([[len(record.sequence)] for record in records], dtype=np.float64)


__all__ = ["extract_length"]
