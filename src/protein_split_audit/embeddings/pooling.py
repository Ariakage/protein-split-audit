# SPDX-License-Identifier: Apache-2.0

"""Residue-only last-layer mean pooling."""

from __future__ import annotations

import torch


def residue_mean_pool(
    hidden: torch.Tensor,
    attention_mask: torch.Tensor,
    special_tokens_mask: torch.Tensor,
) -> torch.Tensor:
    """Mean-pool attended non-special tokens into finite float32 vectors."""

    if hidden.ndim != 3:
        raise ValueError("hidden state must have shape [batch, tokens, hidden]")
    expected_mask_shape = hidden.shape[:2]
    if (
        attention_mask.shape != expected_mask_shape
        or special_tokens_mask.shape != expected_mask_shape
    ):
        raise ValueError("attention and special-token masks must match hidden token shape")
    residue_mask = attention_mask.bool() & ~special_tokens_mask.bool()
    counts = residue_mask.sum(dim=1)
    if bool(torch.any(counts == 0)):
        raise ValueError("one or more rows have no residue tokens")
    values = hidden.to(dtype=torch.float32)
    pooled = (values * residue_mask.unsqueeze(-1)).sum(dim=1) / counts.unsqueeze(-1)
    if not bool(torch.isfinite(pooled).all()):
        raise ValueError("pooled embeddings contain non-finite values")
    return pooled.to(dtype=torch.float32)


__all__ = ["residue_mean_pool"]
