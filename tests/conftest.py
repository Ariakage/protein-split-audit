# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: MonkeyPatch) -> Iterator[None]:
    """Fail tests that attempt to open a real network connection."""

    def blocked_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is disabled in the test suite")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    yield
