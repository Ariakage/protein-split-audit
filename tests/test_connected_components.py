# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import random
from dataclasses import replace
from decimal import Decimal

import pytest

from protein_split_audit.similarity.parse_clusters import SequenceNode, SimilarityEdge


def _nodes() -> tuple[SequenceNode, ...]:
    return (
        SequenceNode(accession="ZETA", sequence_sha256="a" * 64),
        SequenceNode(accession="ALPHA", sequence_sha256="b" * 64),
        SequenceNode(accession="MIDDLE", sequence_sha256="c" * 64),
        SequenceNode(accession="DELTA", sequence_sha256="d" * 64),
        SequenceNode(accession="ISOLATED", sequence_sha256="e" * 64),
    )


def _edge(left: SequenceNode, right: SequenceNode, fident: str) -> SimilarityEdge:
    return SimilarityEdge(
        left=left,
        right=right,
        query_accession=left.accession,
        target_accession=right.accession,
        fident=Decimal(fident),
        qcov=Decimal("0.90"),
        tcov=Decimal("0.90"),
        evalue=Decimal("1e-8"),
        bits=Decimal("80"),
    )


def _component_id(token: str, *nodes: SequenceNode) -> str:
    digest_input = "".join(
        f"{node.sequence_sha256}\n" for node in sorted(nodes, key=lambda item: item.sequence_sha256)
    ).encode("ascii")
    return f"component-{token}-{hashlib.sha256(digest_input).hexdigest()}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fident", Decimal("NaN")),
        ("qcov", Decimal("0.79")),
        ("qcov", Decimal("1.01")),
        ("tcov", Decimal("Infinity")),
        ("evalue", Decimal("0.0011")),
        ("evalue", Decimal("Infinity")),
        ("bits", Decimal("NaN")),
        ("bits", Decimal("-1")),
    ],
)
def test_similarity_edge_enforces_observed_edge_predicate(
    field: str,
    value: Decimal,
) -> None:
    left, right, *_ = _nodes()
    values = {
        "left": left,
        "right": right,
        "query_accession": left.accession,
        "target_accession": right.accession,
        "fident": Decimal("0.50"),
        "qcov": Decimal("0.80"),
        "tcov": Decimal("0.80"),
        "evalue": Decimal("0.001"),
        "bits": Decimal("0"),
    }
    values[field] = value

    with pytest.raises(ValueError, match="similarity edge"):
        SimilarityEdge(**values)  # type: ignore[arg-type]


def test_build_components_keeps_singletons_with_stable_ids_and_representatives() -> None:
    from protein_split_audit.similarity.connected_components import build_components

    nodes = _nodes()
    partition = build_components(nodes, (), Decimal("0.70"))

    assert partition.threshold == Decimal("0.70")
    assert len(partition.rows) == len(nodes)
    assert partition.rows == tuple(
        sorted(partition.rows, key=lambda row: (row.component_id, row.node.accession))
    )
    for row in partition.rows:
        assert row.component_id == _component_id("70", row.node)
        assert row.representative == row.node
        assert row.component_size == 1
        assert partition.node_to_component[row.node] == row.component_id


def test_build_components_rejects_empty_node_collection() -> None:
    from protein_split_audit.similarity.connected_components import build_components

    with pytest.raises(ValueError, match="at least one"):
        build_components((), (), Decimal("0.70"))


def test_build_components_uses_threshold_inclusive_transitive_connectivity() -> None:
    from protein_split_audit.similarity.connected_components import build_components

    first, second, third, fourth, isolated = _nodes()
    edges = (
        _edge(first, second, "0.71"),
        _edge(second, third, "0.70"),
        _edge(third, fourth, "0.69"),
    )

    partition = build_components(_nodes(), edges, Decimal("0.70"))

    merged_id = _component_id("70", first, second, third)
    assert partition.node_to_component[first] == merged_id
    assert partition.node_to_component[second] == merged_id
    assert partition.node_to_component[third] == merged_id
    assert partition.node_to_component[fourth] == _component_id("70", fourth)
    assert partition.node_to_component[isolated] == _component_id("70", isolated)

    merged_rows = tuple(row for row in partition.rows if row.component_id == merged_id)
    assert {row.representative for row in merged_rows} == {second}
    assert {row.component_size for row in merged_rows} == {3}


def test_build_components_is_stable_under_shuffles_and_duplicate_edges() -> None:
    from protein_split_audit.similarity.connected_components import build_components

    nodes = list(_nodes())
    edges = [
        _edge(nodes[0], nodes[1], "0.75"),
        _edge(nodes[1], nodes[2], "0.55"),
        _edge(nodes[2], nodes[3], "0.35"),
    ]
    baseline = build_components(nodes, edges, Decimal("0.30"))

    generator = random.Random(42)
    for _ in range(12):
        shuffled_nodes = nodes.copy()
        shuffled_edges = [*edges, edges[0], edges[2]]
        generator.shuffle(shuffled_nodes)
        generator.shuffle(shuffled_edges)

        assert (
            build_components(
                shuffled_nodes,
                shuffled_edges,
                Decimal("0.30"),
            )
            == baseline
        )


@pytest.mark.parametrize(
    "threshold",
    [
        Decimal("0.29"),
        Decimal("0.31"),
        Decimal("0.69"),
        Decimal("0.71"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        0.70,
    ],
)
def test_build_components_rejects_unapproved_thresholds(threshold: object) -> None:
    from protein_split_audit.similarity.connected_components import build_components

    with pytest.raises(ValueError, match="threshold"):
        build_components(_nodes(), (), threshold)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "nodes",
    [
        (
            SequenceNode(accession="DUPLICATE", sequence_sha256="a" * 64),
            SequenceNode(accession="DUPLICATE", sequence_sha256="b" * 64),
        ),
        (
            SequenceNode(accession="FIRST", sequence_sha256="a" * 64),
            SequenceNode(accession="SECOND", sequence_sha256="a" * 64),
        ),
    ],
)
def test_build_components_rejects_duplicate_node_identities(
    nodes: tuple[SequenceNode, SequenceNode],
) -> None:
    from protein_split_audit.similarity.connected_components import build_components

    with pytest.raises(ValueError, match="duplicate"):
        build_components(nodes, (), Decimal("0.70"))


def test_build_components_rejects_unknown_edge_endpoint() -> None:
    from protein_split_audit.similarity.connected_components import build_components

    nodes = _nodes()
    unknown = SequenceNode(accession="UNKNOWN", sequence_sha256="f" * 64)

    with pytest.raises(ValueError, match="unknown edge endpoint"):
        build_components(
            nodes,
            (_edge(nodes[0], unknown, "0.90"),),
            Decimal("0.70"),
        )


def test_component_digest_has_sorted_hashes_and_final_newline() -> None:
    from protein_split_audit.similarity.connected_components import build_components

    first, second, *_ = _nodes()
    partition = build_components(
        (second, first),
        (_edge(second, first, "0.80"),),
        Decimal("0.70"),
    )
    expected_digest = hashlib.sha256(
        (first.sequence_sha256 + "\n" + second.sequence_sha256 + "\n").encode("utf-8")
    ).hexdigest()

    assert {row.component_id for row in partition.rows} == {f"component-70-{expected_digest}"}


def test_component_partition_rejects_empty_or_internally_inconsistent_rows() -> None:
    from protein_split_audit.similarity.connected_components import (
        ComponentPartition,
        build_components,
    )

    with pytest.raises(ValueError, match="component partition"):
        ComponentPartition(threshold=Decimal("0.70"), rows=())

    first, second, *_ = _nodes()
    valid = build_components(
        (first, second),
        (_edge(first, second, "0.80"),),
        Decimal("0.70"),
    )
    base_row, *remaining_rows = valid.rows
    invalid_rows = (
        replace(base_row, component_id=f"component-70-{'0' * 64}"),
        replace(base_row, representative=first),
        replace(base_row, component_size=99),
    )
    for invalid_row in invalid_rows:
        with pytest.raises(ValueError, match="component partition"):
            ComponentPartition(
                threshold=Decimal("0.70"),
                rows=(invalid_row, *remaining_rows),
            )


def test_validate_nested_components_accepts_70_to_50_to_30_hierarchy() -> None:
    from protein_split_audit.similarity.connected_components import (
        build_components,
        validate_nested_components,
    )

    nodes = _nodes()
    edges = (
        _edge(nodes[0], nodes[1], "0.75"),
        _edge(nodes[1], nodes[2], "0.55"),
        _edge(nodes[2], nodes[3], "0.35"),
    )
    p70 = build_components(nodes, edges, Decimal("0.70"))
    p50 = build_components(nodes, edges, Decimal("0.50"))
    p30 = build_components(nodes, edges, Decimal("0.30"))

    assert validate_nested_components(p70, p50, p30) is None


def test_validate_nested_components_rejects_fine_component_spanning_coarse() -> None:
    from protein_split_audit.similarity.connected_components import (
        build_components,
        validate_nested_components,
    )

    first, second, third, *_ = _nodes()
    nodes = (first, second, third)
    p70 = build_components(nodes, (_edge(first, second, "0.80"),), Decimal("0.70"))
    p50 = build_components(nodes, (_edge(first, third, "0.80"),), Decimal("0.50"))
    p30 = build_components(
        nodes,
        (_edge(first, third, "0.80"), _edge(third, second, "0.80")),
        Decimal("0.30"),
    )

    with pytest.raises(ValueError, match="not nested"):
        validate_nested_components(p70, p50, p30)


def test_validate_nested_components_rejects_wrong_threshold_order_or_node_set() -> None:
    from protein_split_audit.similarity.connected_components import (
        build_components,
        validate_nested_components,
    )

    nodes = _nodes()
    p70 = build_components(nodes, (), Decimal("0.70"))
    p50 = build_components(nodes, (), Decimal("0.50"))
    p30 = build_components(nodes, (), Decimal("0.30"))

    with pytest.raises(ValueError, match="threshold"):
        validate_nested_components(p50, p70, p30)

    smaller_p30 = build_components(nodes[:-1], (), Decimal("0.30"))
    with pytest.raises(ValueError, match="same nodes"):
        validate_nested_components(p70, p50, smaller_p30)
