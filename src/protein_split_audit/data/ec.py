# SPDX-License-Identifier: Apache-2.0

"""Pure EC-annotation parsing for v0.1.0 candidate selection."""

from __future__ import annotations

import re
from dataclasses import dataclass

COMPLETE_EC_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
INCOMPLETE_EC_PATTERN = re.compile(r"^(?:\d+|-)(?:\.(?:\d+|-)){1,3}$")


@dataclass(frozen=True, slots=True)
class EcParseResult:
    """One accepted EC label or one terminal rejection reason."""

    ec_number: str | None
    ec_level_2: str | None
    rejection_reason: str | None


def parse_ec_annotation(value: str | None) -> EcParseResult:
    """Accept exactly one complete four-level EC annotation."""

    normalized = "" if value is None else value.strip()
    if not normalized:
        return EcParseResult(None, None, "missing_ec")

    tokens = [token.strip() for token in normalized.split(";") if token.strip()]
    if len(tokens) != 1:
        return EcParseResult(None, None, "multiple_ec")

    token = tokens[0]
    if COMPLETE_EC_PATTERN.fullmatch(token):
        first, second, _third, _fourth = token.split(".")
        return EcParseResult(token, f"{first}.{second}", None)

    if INCOMPLETE_EC_PATTERN.fullmatch(token) and ("-" in token or token.count(".") < 3):
        return EcParseResult(None, None, "incomplete_ec")
    return EcParseResult(None, None, "malformed_ec")
