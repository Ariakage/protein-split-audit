# SPDX-License-Identifier: Apache-2.0

"""Deterministic batched embedding extraction orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import torch

from protein_split_audit.embeddings.batching import (
    BatchingStatistics,
    batching_statistics,
    deterministic_batches,
)
from protein_split_audit.embeddings.pooling import residue_mean_pool
from protein_split_audit.embeddings.tokenizer import TokenizerAdapter, tokenize_records
from protein_split_audit.features.validation import SequenceRecord


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Canonical matrix and aggregate batching facts."""

    matrix: npt.NDArray[np.float32]
    accessions: tuple[str, ...]
    batching: BatchingStatistics


def extract_embedding_matrix(
    records: Sequence[SequenceRecord],
    tokenizer: TokenizerAdapter,
    encoder: Any,
    *,
    max_padded_tokens: int,
    device: str,
) -> ExtractionResult:
    """Extract pooled embeddings and restore canonical input-record order."""

    if not records:
        raise ValueError("embedding extraction requires at least one record")
    accessions = tuple(record.accession for record in records)
    if len(set(accessions)) != len(accessions):
        raise ValueError("embedding extraction accessions must be unique")
    tokenized = tokenize_records(records, tokenizer)
    batches = deterministic_batches(tokenized, max_padded_tokens)
    pad_token_id = tokenizer.pad_token_id  # type: ignore[attr-defined]
    if pad_token_id is None:
        raise ValueError("tokenizer has no padding token ID")
    by_accession: dict[str, npt.NDArray[np.float32]] = {}
    with torch.inference_mode():
        for batch in batches:
            maximum_length = max(record.encoded_length for record in batch.records)
            input_ids = torch.full(
                (len(batch.records), maximum_length),
                int(pad_token_id),
                dtype=torch.long,
                device=device,
            )
            attention = torch.zeros_like(input_ids)
            special = torch.ones_like(input_ids)
            for row_index, record in enumerate(batch.records):
                length = record.encoded_length
                input_ids[row_index, :length] = torch.tensor(
                    record.input_ids, dtype=torch.long, device=device
                )
                attention[row_index, :length] = 1
                special[row_index, :length] = torch.tensor(
                    record.special_tokens_mask, dtype=torch.long, device=device
                )
            output = encoder(input_ids=input_ids, attention_mask=attention)
            hidden = getattr(output, "last_hidden_state", None)
            if not isinstance(hidden, torch.Tensor):
                raise ValueError("ESM encoder did not return last_hidden_state")
            pooled = residue_mean_pool(hidden, attention, special).cpu().numpy()
            for row_index, record in enumerate(batch.records):
                by_accession[record.accession] = np.asarray(pooled[row_index], dtype=np.float32)
    try:
        matrix = np.stack([by_accession[accession] for accession in accessions]).astype(
            np.float32, copy=False
        )
    except KeyError as error:
        raise ValueError("embedding extraction did not return every input record") from error
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        raise ValueError("embedding extraction returned an invalid matrix")
    return ExtractionResult(matrix, accessions, batching_statistics(batches))


__all__ = ["ExtractionResult", "extract_embedding_matrix"]
