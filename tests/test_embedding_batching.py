# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.embeddings.batching import (
    batching_statistics,
    deterministic_batches,
)
from protein_split_audit.embeddings.tokenizer import TokenizedRecord


def _record(accession: str, encoded_length: int, digest_byte: int) -> TokenizedRecord:
    return TokenizedRecord(
        accession=accession,
        sequence_sha256=bytes([digest_byte]) * 32,
        partition="train",
        input_ids=tuple(range(encoded_length)),
        special_tokens_mask=(True, *(False for _ in range(encoded_length - 2)), True),
    )


def test_deterministic_batches_sort_by_encoded_length_then_hash() -> None:
    records = (
        _record("later", 5, 2),
        _record("long", 7, 0),
        _record("first", 5, 1),
    )

    batches = deterministic_batches(records, max_padded_tokens=10)

    assert [[record.accession for record in batch.records] for batch in batches] == [
        ["first", "later"],
        ["long"],
    ]
    assert [batch.padded_token_count for batch in batches] == [10, 7]
    assert all(not batch.over_budget_exception for batch in batches)


def test_single_oversized_valid_record_is_isolated_and_reported() -> None:
    batches = deterministic_batches((_record("only", 11, 1),), max_padded_tokens=10)
    summary = batching_statistics(batches)

    assert len(batches) == 1
    assert batches[0].over_budget_exception is True
    assert summary.over_budget_singleton_count == 1
    assert summary.maximum_padded_token_cost == 11


def test_batching_statistics_use_actual_padded_shape() -> None:
    batches = deterministic_batches(
        (_record("short", 4, 1), _record("longer", 5, 2)),
        max_padded_tokens=10,
    )

    summary = batching_statistics(batches)

    assert summary.batch_count == 1
    assert summary.maximum_batch_size == 2
    assert summary.maximum_encoded_length == 5
    assert summary.mean_padded_token_cost == 10.0
    assert summary.padding_efficiency == 0.9
