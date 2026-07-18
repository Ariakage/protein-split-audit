# SPDX-License-Identifier: Apache-2.0

"""Validated tokenizer boundary for residue-level ESM inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from protein_split_audit.attestations.test_access import (
    VerifiedTestAuthorization,
    require_verified_authorization,
)
from protein_split_audit.features.validation import SequenceRecord


class TokenizerAdapter(Protocol):
    """Small tokenizer surface used by deterministic extraction."""

    model_max_length: int
    unk_token_id: int | None

    def __call__(self, sequence: str, **kwargs: object) -> Mapping[str, Sequence[int]]: ...


@dataclass(frozen=True, slots=True)
class TokenizedRecord:
    """One unpadded encoded sequence with its special-token mask."""

    accession: str
    sequence_sha256: bytes
    partition: Literal["train", "validation", "test"]
    input_ids: tuple[int, ...]
    special_tokens_mask: tuple[bool, ...]

    @property
    def encoded_length(self) -> int:
        """Return the actual model token length including special tokens."""

        return len(self.input_ids)


def _tokenize_records(
    records: Sequence[SequenceRecord],
    tokenizer: TokenizerAdapter,
    *,
    allowed_partitions: frozenset[str],
) -> tuple[TokenizedRecord, ...]:
    """Encode sequences after the caller fixes the allowed partition boundary."""

    result: list[TokenizedRecord] = []
    for record in records:
        if not 50 <= len(record.sequence) <= 1000:
            raise ValueError(f"sequence length is outside 50-1000: {record.accession}")
        if record.split not in allowed_partitions:
            raise ValueError(f"embedding input partition is not authorized: {record.accession}")
        encoded = tokenizer(
            record.sequence,
            add_special_tokens=True,
            truncation=False,
            return_attention_mask=True,
            return_special_tokens_mask=True,
        )
        try:
            input_ids = tuple(int(value) for value in encoded["input_ids"])
            attention_mask = tuple(bool(value) for value in encoded["attention_mask"])
            special_tokens_mask = tuple(bool(value) for value in encoded["special_tokens_mask"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"tokenizer returned an invalid encoding: {record.accession}"
            ) from error
        if not input_ids or not (len(input_ids) == len(attention_mask) == len(special_tokens_mask)):
            raise ValueError(f"tokenizer output shape mismatch: {record.accession}")
        if len(input_ids) > tokenizer.model_max_length:
            raise ValueError(
                f"encoded sequence exceeds model maximum positions: {record.accession}"
            )
        residue_positions = tuple(
            index
            for index, (attended, special) in enumerate(
                zip(attention_mask, special_tokens_mask, strict=True)
            )
            if attended and not special
        )
        if len(residue_positions) != len(record.sequence):
            raise ValueError(f"residue-token count mismatch: {record.accession}")
        if tokenizer.unk_token_id is not None and any(
            input_ids[index] == tokenizer.unk_token_id for index in residue_positions
        ):
            raise ValueError(f"unknown token in residue positions: {record.accession}")
        result.append(
            TokenizedRecord(
                accession=record.accession,
                sequence_sha256=record.sequence_sha256,
                partition=cast(Literal["train", "validation", "test"], record.split),
                input_ids=input_ids,
                special_tokens_mask=special_tokens_mask,
            )
        )
    return tuple(result)


def tokenize_records(
    records: Sequence[SequenceRecord],
    tokenizer: TokenizerAdapter,
) -> tuple[TokenizedRecord, ...]:
    """Encode validated Train/Validation sequences only."""

    return _tokenize_records(
        records,
        tokenizer,
        allowed_partitions=frozenset({"train", "validation"}),
    )


def tokenize_frozen_test_records(
    records: Sequence[SequenceRecord],
    tokenizer: TokenizerAdapter,
    authorization: VerifiedTestAuthorization,
) -> tuple[TokenizedRecord, ...]:
    """Encode Train/Test sequences only after verifying the opaque capability."""

    require_verified_authorization(authorization)
    return _tokenize_records(
        records,
        tokenizer,
        allowed_partitions=frozenset({"train", "test"}),
    )


__all__ = [
    "TokenizedRecord",
    "TokenizerAdapter",
    "tokenize_frozen_test_records",
    "tokenize_records",
]
