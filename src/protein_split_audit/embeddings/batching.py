# SPDX-License-Identifier: Apache-2.0

"""Stable greedy packing by actual padded token cost."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from protein_split_audit.embeddings.tokenizer import TokenizedRecord


@dataclass(frozen=True, slots=True)
class TokenBatch:
    """One deterministic unpadded-record batch."""

    records: tuple[TokenizedRecord, ...]
    padded_token_count: int
    over_budget_exception: bool = False


@dataclass(frozen=True, slots=True)
class BatchingStatistics:
    """Aggregate padding behavior recorded in embedding provenance."""

    batch_count: int
    maximum_batch_size: int
    maximum_encoded_length: int
    maximum_padded_token_cost: int
    mean_padded_token_cost: float
    padding_efficiency: float
    over_budget_singleton_count: int


def _make_batch(records: Sequence[TokenizedRecord], *, max_padded_tokens: int) -> TokenBatch:
    if not records:
        raise ValueError("cannot create an empty token batch")
    cost = len(records) * max(record.encoded_length for record in records)
    exception = len(records) == 1 and cost > max_padded_tokens
    if cost > max_padded_tokens and not exception:
        raise ValueError("multi-record batch exceeds padded-token budget")
    return TokenBatch(tuple(records), cost, exception)


def deterministic_batches(
    records: Sequence[TokenizedRecord],
    max_padded_tokens: int,
) -> tuple[TokenBatch, ...]:
    """Pack records using stable length/hash ordering and greedy padded cost."""

    if max_padded_tokens <= 0:
        raise ValueError("max_padded_tokens must be positive")
    ordered = sorted(records, key=lambda record: (record.encoded_length, record.sequence_sha256))
    batches: list[TokenBatch] = []
    current: list[TokenizedRecord] = []
    current_max = 0
    for record in ordered:
        if record.encoded_length > max_padded_tokens:
            if current:
                batches.append(_make_batch(current, max_padded_tokens=max_padded_tokens))
                current = []
                current_max = 0
            batches.append(_make_batch((record,), max_padded_tokens=max_padded_tokens))
            continue
        proposed_max = max(current_max, record.encoded_length)
        proposed_cost = (len(current) + 1) * proposed_max
        if current and proposed_cost > max_padded_tokens:
            batches.append(_make_batch(current, max_padded_tokens=max_padded_tokens))
            current = []
            current_max = 0
        current.append(record)
        current_max = max(current_max, record.encoded_length)
    if current:
        batches.append(_make_batch(current, max_padded_tokens=max_padded_tokens))
    return tuple(batches)


def batching_statistics(batches: Sequence[TokenBatch]) -> BatchingStatistics:
    """Summarize deterministic batches without record identifiers."""

    if not batches:
        raise ValueError("cannot summarize zero token batches")
    total_encoded = sum(record.encoded_length for batch in batches for record in batch.records)
    total_padded = sum(batch.padded_token_count for batch in batches)
    return BatchingStatistics(
        batch_count=len(batches),
        maximum_batch_size=max(len(batch.records) for batch in batches),
        maximum_encoded_length=max(
            record.encoded_length for batch in batches for record in batch.records
        ),
        maximum_padded_token_cost=max(batch.padded_token_count for batch in batches),
        mean_padded_token_cost=fmean(batch.padded_token_count for batch in batches),
        padding_efficiency=total_encoded / total_padded,
        over_budget_singleton_count=sum(batch.over_budget_exception for batch in batches),
    )


__all__ = [
    "BatchingStatistics",
    "TokenBatch",
    "batching_statistics",
    "deterministic_batches",
]
