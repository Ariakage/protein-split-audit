# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import numpy as np

from protein_split_audit.statistics.group_bootstrap import domain_group_bootstrap_indices


def test_group_draws_are_repeatable_domain_separated_and_component_complete() -> None:
    groups = ("component-b", "component-a", "component-b")
    first = domain_group_bootstrap_indices(groups, iterations=2000, seed=2026, domain="alpha")
    replay = domain_group_bootstrap_indices(groups, iterations=2000, seed=2026, domain="alpha")
    other = domain_group_bootstrap_indices(groups, iterations=2000, seed=2026, domain="beta")

    assert len(first) == 2000
    assert all(np.array_equal(left, right) for left, right in zip(first, replay, strict=True))
    assert any(not np.array_equal(left, right) for left, right in zip(first, other, strict=True))
    for draw in first:
        assert int(np.count_nonzero(draw == 0)) == int(np.count_nonzero(draw == 2))


def test_group_draw_order_does_not_depend_on_first_seen_component_order() -> None:
    first = domain_group_bootstrap_indices(("z", "a"), iterations=4, seed=42, domain="canonical")
    second = domain_group_bootstrap_indices(("a", "z"), iterations=4, seed=42, domain="canonical")

    first_components = tuple(tuple(("z", "a")[int(index)] for index in draw) for draw in first)
    second_components = tuple(tuple(("a", "z")[int(index)] for index in draw) for draw in second)
    assert first_components == second_components
