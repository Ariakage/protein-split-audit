# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq

from protein_split_audit.similarity.connected_components import build_components
from protein_split_audit.similarity.parse_clusters import (
    NativeClusterMembership,
    SequenceNode,
    SimilarityEdge,
)


def _graph() -> tuple[tuple[SequenceNode, ...], tuple[SimilarityEdge, ...]]:
    nodes = tuple(
        SequenceNode(accession=f"P{index}", sequence_sha256=character * 64)
        for index, character in enumerate("abcd", start=1)
    )

    def edge(left: int, right: int, identity: str) -> SimilarityEdge:
        return SimilarityEdge(
            left=nodes[left],
            right=nodes[right],
            query_accession=nodes[left].accession,
            target_accession=nodes[right].accession,
            fident=Decimal(identity),
            qcov=Decimal("0.90"),
            tcov=Decimal("0.90"),
            evalue=Decimal("1e-10"),
            bits=Decimal("80"),
        )

    return nodes, (edge(0, 1, "0.80"), edge(1, 2, "0.60"), edge(2, 3, "0.40"))


def test_serialize_formal_similarity_keeps_native_and_strict_groups_distinct() -> None:
    from protein_split_audit.similarity.formal import (
        FORMAL_CLUSTER_SCHEMA,
        serialize_formal_similarity,
    )

    nodes, edges = _graph()
    partition = build_components(nodes, edges, Decimal("0.50"))
    native = tuple(NativeClusterMembership(representative=nodes[0], member=node) for node in nodes)

    first = serialize_formal_similarity(
        native,
        partition,
        ec_level_2_by_accession={node.accession: "2.7" for node in nodes},
        mmseqs_version="18-8cc5c",
        cohort_version="pilot-v1",
    )
    second = serialize_formal_similarity(
        tuple(reversed(native)),
        partition,
        ec_level_2_by_accession={node.accession: "2.7" for node in reversed(nodes)},
        mmseqs_version="18-8cc5c",
        cohort_version="pilot-v1",
    )

    assert first == second
    table = pq.read_table(pa.BufferReader(first.parquet_bytes))
    assert table.schema.equals(FORMAL_CLUSTER_SCHEMA, check_metadata=False)
    assert table.column("cluster_id").to_pylist() == ["P1", "P1", "P1", "P1"]
    assert len(set(table.column("similarity_component_id").to_pylist())) == 2


def test_validate_similarity_matrix_accepts_one_shared_edge_table() -> None:
    from protein_split_audit.similarity.formal import validate_similarity_matrix

    nodes, edges = _graph()
    p70 = build_components(nodes, edges, Decimal("0.70"))
    p50 = build_components(nodes, edges, Decimal("0.50"))
    p30 = build_components(nodes, edges, Decimal("0.30"))

    report = validate_similarity_matrix(p70, p50, p30, expected_nodes=nodes)

    assert report == {"cluster70": 3, "cluster50": 2, "cluster30": 1}
