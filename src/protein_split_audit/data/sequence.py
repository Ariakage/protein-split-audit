# SPDX-License-Identifier: Apache-2.0

"""Pure protein-sequence normalization and validation."""

from __future__ import annotations

from dataclasses import dataclass

from protein_split_audit.provenance import sha256_bytes

STANDARD_AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


@dataclass(frozen=True, slots=True)
class SequenceValidationResult:
    """A normalized sequence outcome with no silent filtering."""

    sequence: str
    sequence_length: int
    sequence_sha256: str | None
    rejection_reason: str | None


def validate_sequence(
    value: str | None,
    *,
    min_length: int,
    max_length: int,
    allowed_amino_acids: str = STANDARD_AMINO_ACIDS,
) -> SequenceValidationResult:
    """Normalize with strip/uppercase and enforce alphabet and inclusive length bounds."""

    normalized = "" if value is None else value.strip().upper()
    length = len(normalized)
    if not normalized:
        return SequenceValidationResult(normalized, length, None, "missing_sequence")
    if any(character not in allowed_amino_acids for character in normalized):
        return SequenceValidationResult(
            normalized,
            length,
            None,
            "invalid_sequence_characters",
        )
    if length < min_length:
        return SequenceValidationResult(normalized, length, None, "sequence_too_short")
    if length > max_length:
        return SequenceValidationResult(normalized, length, None, "sequence_too_long")
    return SequenceValidationResult(
        normalized,
        length,
        sha256_bytes(normalized.encode("ascii")),
        None,
    )
