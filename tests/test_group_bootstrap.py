# SPDX-License-Identifier: Apache-2.0

import numpy as np
import pytest

from protein_split_audit.experiments.schemas import BootstrapSpec
from protein_split_audit.statistics.group_bootstrap import group_bootstrap_indices


def _spec() -> BootstrapSpec:
    return BootstrapSpec(
        iterations=2000,
        confidence_level=0.95,
        lower_quantile=0.025,
        upper_quantile=0.975,
        seed=2026,
        unit="cluster30_discovery_component",
        interval_method="percentile",
        quantile_method="linear",
    )


def test_group_bootstrap_samples_complete_components_with_replacement() -> None:
    groups = ("a", "a", "b", "c", "c", "c")

    draws = group_bootstrap_indices(groups, _spec(), "random:macro_f1:majority")

    assert len(draws) == 2000
    assert all(draw.dtype == np.int64 for draw in draws)
    assert any(len(draw) != len(groups) for draw in draws)
    for draw in draws[:50]:
        counts = {index: int(np.count_nonzero(draw == index)) for index in range(len(groups))}
        assert counts[0] == counts[1]
        assert counts[3] == counts[4] == counts[5]


def test_group_bootstrap_is_domain_separated_and_deterministic() -> None:
    groups = ("a", "a", "b", "c", "c", "c")

    first = group_bootstrap_indices(groups, _spec(), "random:macro_f1:majority")
    repeated = group_bootstrap_indices(groups, _spec(), "random:macro_f1:majority")
    other = group_bootstrap_indices(groups, _spec(), "cluster30:macro_f1:majority")

    assert [draw.tolist() for draw in first[:3]] == [
        [2, 3, 4, 5, 0, 1],
        [0, 1, 2, 0, 1],
        [0, 1, 2, 2],
    ]
    assert [draw.tolist() for draw in first[:3]] == [draw.tolist() for draw in repeated[:3]]
    assert [draw.tolist() for draw in first[:3]] != [draw.tolist() for draw in other[:3]]


@pytest.mark.parametrize("groups", [(), ("a", ""), ("a", "unknown")])
def test_group_bootstrap_rejects_missing_component_identity(groups: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="component"):
        group_bootstrap_indices(groups, _spec(), "domain")
