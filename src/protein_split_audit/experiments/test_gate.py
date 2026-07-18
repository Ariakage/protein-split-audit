# SPDX-License-Identifier: Apache-2.0

"""Deny real Test access under the v0.3.0 protocol attestation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml


class RealTestAccessDenied(RuntimeError):
    """Raised before any real Test input is opened."""


def enforce_test_gate(
    attestation: Path,
    *,
    before_real_input: Callable[[], None] | None = None,
) -> None:
    """Read authorization first and deny v0.3.0 Test access."""

    try:
        mapping: Any = yaml.safe_load(attestation.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RealTestAccessDenied(
            "Real test access is not authorized by the active attestation"
        ) from error
    del mapping, before_real_input
    raise RealTestAccessDenied("Real test access is not authorized by the active attestation")


__all__ = ["RealTestAccessDenied", "enforce_test_gate"]
