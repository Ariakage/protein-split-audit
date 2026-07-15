# SPDX-License-Identifier: Apache-2.0

"""Strict parsing and normalization for MMseqs2 format-mode-4 pair tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

_HEADER = "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits"
_MIN_COVERAGE = Decimal("0.80")
_MAX_EVALUE = Decimal("0.001")
_ZERO = Decimal(0)
_ONE = Decimal(1)
_LOWER_HEX = frozenset("0123456789abcdef")


class PairTsvError(RuntimeError):
    """Raised when an MMseqs2 pair table violates the parser contract."""


def _is_finite_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


@dataclass(frozen=True, slots=True)
class SequenceNode:
    """One accession/hash identity used by MMseqs2 and component construction."""

    accession: str
    sequence_sha256: str

    def __post_init__(self) -> None:
        if not self.accession or self.accession.strip() != self.accession:
            msg = "sequence node accession must be non-empty without surrounding whitespace"
            raise ValueError(msg)
        if len(self.sequence_sha256) != 64 or any(
            character not in _LOWER_HEX for character in self.sequence_sha256
        ):
            msg = "sequence node hash must be a lowercase 64-character SHA-256 digest"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, init=False)
class CandidateIndex:
    """Immutable lookup from MMseqs2 identifiers to sequence identities."""

    nodes: tuple[SequenceNode, ...]
    _by_search_id: Mapping[str, SequenceNode] = field(repr=False, compare=False)

    def __init__(self, nodes: Sequence[SequenceNode]) -> None:
        normalized = tuple(nodes)
        if not normalized:
            msg = "candidate index must contain at least one sequence node"
            raise ValueError(msg)

        by_search_id: dict[str, SequenceNode] = {}
        hashes: set[str] = set()
        for node in normalized:
            if node.accession in by_search_id:
                msg = f"candidate index contains duplicate accession {node.accession!r}"
                raise ValueError(msg)
            if node.sequence_sha256 in hashes:
                msg = "candidate index contains a duplicate sequence hash"
                raise ValueError(msg)
            by_search_id[node.accession] = node
            hashes.add(node.sequence_sha256)

        ordered = tuple(sorted(normalized, key=lambda node: (node.accession, node.sequence_sha256)))
        object.__setattr__(self, "nodes", ordered)
        object.__setattr__(self, "_by_search_id", MappingProxyType(by_search_id))

    @classmethod
    def from_nodes(cls, nodes: Sequence[SequenceNode]) -> CandidateIndex:
        """Build a lookup from verified sequence nodes."""

        return cls(nodes)

    def resolve(self, search_id: str) -> SequenceNode:
        """Return the sequence node associated with an MMseqs2 identifier."""

        try:
            return self._by_search_id[search_id]
        except KeyError as error:
            msg = f"pair table contains unknown sequence identifier {search_id!r}"
            raise PairTsvError(msg) from error


@dataclass(frozen=True, slots=True)
class SimilarityEdge:
    """One normalized undirected pair retaining its best directed observation."""

    left: SequenceNode
    right: SequenceNode
    query_accession: str
    target_accession: str
    fident: Decimal
    qcov: Decimal
    tcov: Decimal
    evalue: Decimal
    bits: Decimal

    def __post_init__(self) -> None:
        metrics = (self.fident, self.qcov, self.tcov, self.evalue, self.bits)
        if not all(_is_finite_decimal(value) for value in metrics):
            raise ValueError("similarity edge metrics must be finite Decimal values")
        if not _ZERO <= self.fident <= _ONE:
            raise ValueError("similarity edge identity must be a fraction")
        if not _MIN_COVERAGE <= self.qcov <= _ONE:
            raise ValueError("similarity edge query coverage violates the fixed predicate")
        if not _MIN_COVERAGE <= self.tcov <= _ONE:
            raise ValueError("similarity edge target coverage violates the fixed predicate")
        if not _ZERO <= self.evalue <= _MAX_EVALUE:
            raise ValueError("similarity edge e-value violates the fixed predicate")
        if self.bits < _ZERO:
            raise ValueError("similarity edge bitscore must be non-negative")


@dataclass(frozen=True, slots=True)
class _DirectedHit:
    query: SequenceNode
    target: SequenceNode
    fident: Decimal
    qcov: Decimal
    tcov: Decimal
    evalue: Decimal
    bits: Decimal


def _best_hit_key(
    hit: _DirectedHit,
) -> tuple[Decimal, Decimal, Decimal, Decimal, str, str, Decimal, Decimal]:
    return (
        -hit.fident,
        -min(hit.qcov, hit.tcov),
        -hit.bits,
        hit.evalue,
        hit.query.accession,
        hit.target.accession,
        -hit.qcov,
        -hit.tcov,
    )


def _read_lines(path: Path) -> list[str]:
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        msg = f"pair table not found: {path}"
        raise PairTsvError(msg) from error
    except OSError as error:
        msg = f"pair table could not be read: {path}"
        raise PairTsvError(msg) from error

    if not content:
        raise PairTsvError("pair table is empty")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PairTsvError("pair table must be valid UTF-8") from error
    if "\r" in text or not text.endswith("\n"):
        raise PairTsvError("pair table must use LF line endings and end with LF")

    lines = text[:-1].split("\n")
    if lines[0] != _HEADER:
        raise PairTsvError("pair table header does not match format mode 4")
    if len(lines) == 1:
        raise PairTsvError("pair table must contain at least one hit")
    return lines[1:]


def _parse_hit(line: str, line_number: int, expected: CandidateIndex) -> _DirectedHit:
    if line == _HEADER:
        msg = f"pair table repeats its header on line {line_number}"
        raise PairTsvError(msg)
    fields = line.split("\t")
    if len(fields) != 7:
        msg = f"pair table line {line_number} must contain exactly seven fields"
        raise PairTsvError(msg)

    query_id, target_id, *numeric_text = fields
    try:
        fident, qcov, tcov, evalue, bits = (Decimal(value) for value in numeric_text)
    except InvalidOperation as error:
        msg = f"pair table line {line_number} contains an invalid numeric value"
        raise PairTsvError(msg) from error
    values = (fident, qcov, tcov, evalue, bits)
    if not all(value.is_finite() for value in values):
        msg = f"pair table line {line_number} contains a non-finite numeric value"
        raise PairTsvError(msg)
    if (
        not _ZERO <= fident <= _ONE
        or not _ZERO <= qcov <= _ONE
        or not _ZERO <= tcov <= _ONE
        or evalue < _ZERO
        or bits < _ZERO
    ):
        msg = f"pair table line {line_number} contains a numeric value outside its range"
        raise PairTsvError(msg)

    return _DirectedHit(
        query=expected.resolve(query_id),
        target=expected.resolve(target_id),
        fident=fident,
        qcov=qcov,
        tcov=tcov,
        evalue=evalue,
        bits=bits,
    )


def _qualifies(hit: _DirectedHit) -> bool:
    return hit.qcov >= _MIN_COVERAGE and hit.tcov >= _MIN_COVERAGE and hit.evalue <= _MAX_EVALUE


def parse_pair_tsv(path: Path, expected: CandidateIndex) -> tuple[SimilarityEdge, ...]:
    """Parse one all-vs-all format-mode-4 table into normalized undirected edges."""

    grouped: dict[tuple[str, str], list[_DirectedHit]] = {}
    qualifying_self_hits: set[str] = set()
    for line_number, line in enumerate(_read_lines(path), start=2):
        hit = _parse_hit(line, line_number, expected)
        if hit.query == hit.target:
            if _qualifies(hit):
                qualifying_self_hits.add(hit.query.sequence_sha256)
            continue
        if not _qualifies(hit):
            continue
        pair = tuple(sorted((hit.query.sequence_sha256, hit.target.sequence_sha256)))
        grouped.setdefault((pair[0], pair[1]), []).append(hit)

    expected_hashes = {node.sequence_sha256 for node in expected.nodes}
    if qualifying_self_hits != expected_hashes:
        missing = len(expected_hashes - qualifying_self_hits)
        msg = f"pair table is missing a qualifying self hit for {missing} sequence(s)"
        raise PairTsvError(msg)

    edges: list[SimilarityEdge] = []
    for pair in sorted(grouped):
        best = min(grouped[pair], key=_best_hit_key)
        nodes = sorted((best.query, best.target), key=lambda node: node.sequence_sha256)
        edges.append(
            SimilarityEdge(
                left=nodes[0],
                right=nodes[1],
                query_accession=best.query.accession,
                target_accession=best.target.accession,
                fident=best.fident,
                qcov=best.qcov,
                tcov=best.tcov,
                evalue=best.evalue,
                bits=best.bits,
            )
        )
    return tuple(edges)


__all__ = [
    "CandidateIndex",
    "PairTsvError",
    "SequenceNode",
    "SimilarityEdge",
    "parse_pair_tsv",
]
