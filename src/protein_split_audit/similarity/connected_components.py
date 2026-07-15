# SPDX-License-Identifier: Apache-2.0

"""Deterministic observed-edge similarity components and nesting validation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from protein_split_audit.similarity.parse_clusters import SequenceNode, SimilarityEdge

_THRESHOLD_TOKENS = MappingProxyType(
    {
        Decimal("0.70"): "70",
        Decimal("0.50"): "50",
        Decimal("0.30"): "30",
    }
)
_ZERO = Decimal(0)
_ONE = Decimal(1)


class ComponentError(ValueError):
    """Raised when component inputs or partitions violate their contract."""


@dataclass(frozen=True, slots=True)
class ComponentMembership:
    """One deterministic row in a similarity component partition."""

    node: SequenceNode
    component_id: str
    representative: SequenceNode
    component_size: int


@dataclass(frozen=True, slots=True)
class ComponentPartition:
    """Immutable component membership rows for one approved identity threshold."""

    threshold: Decimal
    rows: tuple[ComponentMembership, ...]
    _node_to_component: Mapping[SequenceNode, str] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        token = _threshold_token(self.threshold)
        ordered = tuple(
            sorted(
                self.rows,
                key=lambda row: (
                    row.component_id,
                    row.node.accession,
                    row.node.sequence_sha256,
                ),
            )
        )
        if not ordered:
            raise ComponentError("component partition must contain at least one row")
        node_to_component: dict[SequenceNode, str] = {}
        accessions: set[str] = set()
        hashes: set[str] = set()
        grouped: dict[str, list[ComponentMembership]] = {}
        for row in ordered:
            if (
                row.node in node_to_component
                or row.node.accession in accessions
                or row.node.sequence_sha256 in hashes
            ):
                raise ComponentError("component partition contains a duplicate node identity")
            node_to_component[row.node] = row.component_id
            accessions.add(row.node.accession)
            hashes.add(row.node.sequence_sha256)
            grouped.setdefault(row.component_id, []).append(row)

        for component_id, component_rows in grouped.items():
            members = tuple(row.node for row in component_rows)
            expected_id = _component_id(token, members)
            representative = min(
                members,
                key=lambda node: (node.accession, node.sequence_sha256),
            )
            component_size = len(members)
            if component_id != expected_id:
                raise ComponentError("component partition contains an invalid component ID")
            if any(row.representative != representative for row in component_rows):
                raise ComponentError("component partition contains an invalid representative")
            if any(row.component_size != component_size for row in component_rows):
                raise ComponentError("component partition contains an invalid component size")

        object.__setattr__(self, "rows", ordered)
        object.__setattr__(
            self,
            "_node_to_component",
            MappingProxyType(node_to_component),
        )

    @property
    def node_to_component(self) -> Mapping[SequenceNode, str]:
        """Return an immutable exact-identity to component-ID lookup."""

        return self._node_to_component


def _threshold_token(threshold: Decimal) -> str:
    if not isinstance(threshold, Decimal):
        raise ComponentError("component threshold must be a Decimal")
    if not threshold.is_finite():
        raise ComponentError("component threshold must be finite")
    try:
        return _THRESHOLD_TOKENS[threshold]
    except KeyError as error:
        msg = "component threshold must be exactly Decimal('0.70'), '0.50', or '0.30'"
        raise ComponentError(msg) from error


def _validate_nodes(nodes: Sequence[SequenceNode]) -> tuple[SequenceNode, ...]:
    normalized = tuple(nodes)
    if not normalized:
        raise ComponentError("component graph must contain at least one node")
    accessions: set[str] = set()
    hashes: set[str] = set()
    for node in normalized:
        if node.accession in accessions:
            msg = f"component nodes contain duplicate accession {node.accession!r}"
            raise ComponentError(msg)
        if node.sequence_sha256 in hashes:
            raise ComponentError("component nodes contain a duplicate sequence hash")
        accessions.add(node.accession)
        hashes.add(node.sequence_sha256)
    return tuple(sorted(normalized, key=lambda node: (node.accession, node.sequence_sha256)))


def _component_id(token: str, members: Sequence[SequenceNode]) -> str:
    digest = hashlib.sha256()
    for sequence_hash in sorted(node.sequence_sha256 for node in members):
        digest.update(sequence_hash.encode("ascii"))
        digest.update(b"\n")
    return f"component-{token}-{digest.hexdigest()}"


def build_components(
    nodes: Sequence[SequenceNode],
    edges: Sequence[SimilarityEdge],
    threshold: Decimal,
) -> ComponentPartition:
    """Build a stable partition from observed normalized edges at ``threshold``."""

    token = _threshold_token(threshold)
    ordered_nodes = _validate_nodes(nodes)
    node_set = set(ordered_nodes)
    parent = {node: node for node in ordered_nodes}

    def find(node: SequenceNode) -> SequenceNode:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != node:
            previous = parent[node]
            parent[node] = root
            node = previous
        return root

    def union(left: SequenceNode, right: SequenceNode) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if (left_root.accession, left_root.sequence_sha256) <= (
            right_root.accession,
            right_root.sequence_sha256,
        ):
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    for edge in edges:
        if edge.left not in node_set or edge.right not in node_set:
            raise ComponentError("component graph contains an unknown edge endpoint")
        if (
            not isinstance(edge.fident, Decimal)
            or not edge.fident.is_finite()
            or not _ZERO <= edge.fident <= _ONE
        ):
            raise ComponentError("component graph edge identity must be a finite fraction")
        if edge.fident >= threshold:
            union(edge.left, edge.right)

    grouped: dict[SequenceNode, list[SequenceNode]] = {}
    for node in ordered_nodes:
        grouped.setdefault(find(node), []).append(node)

    rows: list[ComponentMembership] = []
    for members in grouped.values():
        representative = min(
            members,
            key=lambda node: (node.accession, node.sequence_sha256),
        )
        component_id = _component_id(token, members)
        component_size = len(members)
        rows.extend(
            ComponentMembership(
                node=node,
                component_id=component_id,
                representative=representative,
                component_size=component_size,
            )
            for node in members
        )

    return ComponentPartition(threshold=threshold, rows=tuple(rows))


def _validate_nested_pair(
    fine: ComponentPartition,
    coarse: ComponentPartition,
) -> None:
    coarse_by_fine: dict[str, str] = {}
    for row in fine.rows:
        coarse_id = coarse.node_to_component[row.node]
        previous = coarse_by_fine.setdefault(row.component_id, coarse_id)
        if previous != coarse_id:
            msg = (
                f"component partitions are not nested: {row.component_id!r} "
                "spans multiple coarser components"
            )
            raise ComponentError(msg)


def validate_nested_components(
    p70: ComponentPartition,
    p50: ComponentPartition,
    p30: ComponentPartition,
) -> None:
    """Validate exact node equality and the required 70 -> 50 -> 30 nesting."""

    expected_thresholds = (Decimal("0.70"), Decimal("0.50"), Decimal("0.30"))
    partitions = (p70, p50, p30)
    for partition, expected in zip(partitions, expected_thresholds, strict=True):
        if partition.threshold != expected:
            raise ComponentError("component partitions are not in 70, 50, 30 threshold order")

    node_sets = tuple(set(partition.node_to_component) for partition in partitions)
    if node_sets[0] != node_sets[1] or node_sets[1] != node_sets[2]:
        raise ComponentError("component partitions must contain the same nodes")

    _validate_nested_pair(p70, p50)
    _validate_nested_pair(p50, p30)


__all__ = [
    "ComponentError",
    "ComponentMembership",
    "ComponentPartition",
    "build_components",
    "validate_nested_components",
]
