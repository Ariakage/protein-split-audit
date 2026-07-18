# SPDX-License-Identifier: Apache-2.0

"""Domain-separated component bootstrap draws."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from protein_split_audit.experiments.schemas import BootstrapSpec


def _domain_entropy(domain: str) -> tuple[int, ...]:
    if not domain or domain != domain.strip():
        raise ValueError("bootstrap domain must be a nonblank canonical string")
    digest = hashlib.sha256(domain.encode("utf-8")).digest()
    return tuple(int.from_bytes(digest[index : index + 4], "big") for index in range(0, 16, 4))


def group_bootstrap_indices(
    group_ids: Sequence[str],
    spec: BootstrapSpec,
    domain: str,
) -> tuple[npt.NDArray[np.int64], ...]:
    """Sample component IDs with replacement and expand each to all member rows."""

    return domain_group_bootstrap_indices(
        group_ids,
        iterations=spec.iterations,
        seed=spec.seed,
        domain=domain,
    )


def domain_group_bootstrap_indices(
    group_ids: Sequence[str],
    *,
    iterations: int,
    seed: int,
    domain: str,
) -> tuple[npt.NDArray[np.int64], ...]:
    """Draw complete sorted groups using an explicit domain and seed."""

    groups = tuple(group_ids)
    if not groups or any(
        not isinstance(group, str)
        or not group.strip()
        or group.strip().casefold() in {"unknown", "none", "na", "n/a"}
        for group in groups
    ):
        raise ValueError("every bootstrap row requires one frozen component identity")
    if isinstance(iterations, bool) or iterations < 1:
        raise ValueError("bootstrap iterations must be a positive integer")
    if isinstance(seed, bool) or seed < 0:
        raise ValueError("bootstrap seed must be a nonnegative integer")
    canonical = tuple(sorted(set(groups)))
    members = tuple(
        np.asarray(
            [index for index, group in enumerate(groups) if group == identity],
            dtype=np.int64,
        )
        for identity in canonical
    )
    seed_sequence = np.random.SeedSequence((seed, *_domain_entropy(domain)))
    generator = np.random.default_rng(seed_sequence)
    draws: list[npt.NDArray[np.int64]] = []
    for _ in range(iterations):
        sampled = generator.integers(0, len(canonical), size=len(canonical), dtype=np.int64)
        expanded = np.concatenate([members[int(index)] for index in sampled])
        draws.append(np.asarray(expanded, dtype=np.int64))
    return tuple(draws)


__all__ = ["domain_group_bootstrap_indices", "group_bootstrap_indices"]
