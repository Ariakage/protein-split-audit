# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass

import pytest

from protein_split_audit.embeddings.tokenizer import tokenize_records
from protein_split_audit.features.validation import SequenceRecord


@dataclass
class FakeTokenizer:
    model_max_length: int = 1024
    unk_token_id: int = 99

    def __call__(self, sequence: str, **kwargs: object) -> dict[str, list[int]]:
        assert kwargs["truncation"] is False
        return {
            "input_ids": [0, *(range(5, 5 + len(sequence))), 2],
            "attention_mask": [1] * (len(sequence) + 2),
            "special_tokens_mask": [1, *([0] * len(sequence)), 1],
        }


def _sequence(sequence: str) -> SequenceRecord:
    return SequenceRecord(
        accession="P0",
        sequence_sha256=b"a" * 32,
        label="",
        split="train",
        sequence=sequence,
    )


def test_tokenization_counts_residues_and_includes_bos_eos() -> None:
    tokenized = tokenize_records((_sequence("A" * 50),), FakeTokenizer())

    assert len(tokenized[0].input_ids) == 52
    assert sum(not value for value in tokenized[0].special_tokens_mask) == 50


def test_tokenization_rejects_unknown_residue_token() -> None:
    class UnknownTokenizer(FakeTokenizer):
        def __call__(self, sequence: str, **kwargs: object) -> dict[str, list[int]]:
            result = super().__call__(sequence, **kwargs)
            result["input_ids"][1] = self.unk_token_id
            return result

    with pytest.raises(ValueError, match=r"unknown token.*P0"):
        tokenize_records((_sequence("A" * 50),), UnknownTokenizer())


def test_tokenization_rejects_truncated_or_multi_residue_mapping() -> None:
    class ShortTokenizer(FakeTokenizer):
        def __call__(self, sequence: str, **kwargs: object) -> dict[str, list[int]]:
            result = super().__call__(sequence, **kwargs)
            del result["input_ids"][2]
            del result["attention_mask"][2]
            del result["special_tokens_mask"][2]
            return result

    with pytest.raises(ValueError, match=r"residue-token count mismatch.*P0"):
        tokenize_records((_sequence("A" * 50),), ShortTokenizer())


@pytest.mark.parametrize("length", [49, 1001])
def test_tokenization_enforces_sequence_bounds(length: int) -> None:
    with pytest.raises(ValueError, match="sequence length"):
        tokenize_records((_sequence("A" * length),), FakeTokenizer())
