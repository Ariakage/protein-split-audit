# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from protein_split_audit.embeddings.extract import extract_embedding_matrix
from protein_split_audit.features.validation import SequenceRecord


@dataclass
class FakeTokenizer:
    model_max_length: int = 1024
    unk_token_id: int = 99
    pad_token_id: int = 1

    def __call__(self, sequence: str, **_kwargs: object) -> dict[str, list[int]]:
        return {
            "input_ids": [0, *([5] * len(sequence)), 2],
            "attention_mask": [1] * (len(sequence) + 2),
            "special_tokens_mask": [1, *([0] * len(sequence)), 1],
        }


class FakeEncoder:
    def __call__(self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> object:
        del attention_mask
        hidden = torch.stack(
            (input_ids.float(), input_ids.float() + 1, input_ids.float() + 2), dim=-1
        )
        return type("Output", (), {"last_hidden_state": hidden})()


def _record(accession: str, length: int, digest: int) -> SequenceRecord:
    return SequenceRecord(
        accession=accession,
        sequence_sha256=bytes([digest]) * 32,
        label="",
        split="train",
        sequence="A" * length,
    )


def test_fake_extraction_restores_original_record_order() -> None:
    records = (_record("long", 60, 2), _record("short", 50, 1))

    result = extract_embedding_matrix(
        records,
        FakeTokenizer(),
        FakeEncoder(),
        max_padded_tokens=4096,
        device="cpu",
    )

    assert result.matrix.dtype == np.float32
    assert result.matrix.shape == (2, 3)
    np.testing.assert_array_equal(result.matrix[0], np.asarray([5.0, 6.0, 7.0], dtype=np.float32))
    assert result.accessions == ("long", "short")
    assert result.batching.over_budget_singleton_count == 0
