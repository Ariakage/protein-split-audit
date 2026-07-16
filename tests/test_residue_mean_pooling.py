# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
import torch

from protein_split_audit.embeddings.pooling import residue_mean_pool


def test_residue_mean_pool_excludes_special_and_padding_tokens() -> None:
    hidden = torch.tensor(
        [
            [[100.0, 100.0], [1.0, 3.0], [3.0, 5.0], [200.0, 200.0], [999.0, 999.0]],
            [[100.0, 100.0], [2.0, 4.0], [200.0, 200.0], [999.0, 999.0], [999.0, 999.0]],
        ],
        dtype=torch.float64,
    )
    attention = torch.tensor([[1, 1, 1, 1, 0], [1, 1, 1, 0, 0]])
    special = torch.tensor([[1, 0, 0, 1, 1], [1, 0, 1, 1, 1]])

    pooled = residue_mean_pool(hidden, attention, special)

    assert pooled.dtype == torch.float32
    torch.testing.assert_close(pooled, torch.tensor([[2.0, 4.0], [2.0, 4.0]]))


def test_residue_mean_pool_rejects_rows_without_residues() -> None:
    with pytest.raises(ValueError, match="no residue tokens"):
        residue_mean_pool(
            torch.zeros((1, 2, 3)),
            torch.ones((1, 2), dtype=torch.long),
            torch.ones((1, 2), dtype=torch.long),
        )


def test_residue_mean_pool_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="shape"):
        residue_mean_pool(
            torch.zeros((1, 2, 3)),
            torch.ones((1, 3), dtype=torch.long),
            torch.zeros((1, 2), dtype=torch.long),
        )
