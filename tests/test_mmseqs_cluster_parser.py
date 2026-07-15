# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

HEADER = "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits"


def _nodes() -> tuple[object, object]:
    from protein_split_audit.similarity.parse_clusters import SequenceNode

    return (
        SequenceNode(accession="A00001", sequence_sha256="a" * 64),
        SequenceNode(accession="B00002", sequence_sha256="b" * 64),
    )


def _index(nodes: tuple[object, ...] | None = None) -> object:
    from protein_split_audit.similarity.parse_clusters import CandidateIndex

    selected = _nodes() if nodes is None else nodes
    return CandidateIndex.from_nodes(selected)


def _self_rows() -> list[str]:
    return [
        "A00001\tA00001\t1.0\t1.0\t1.0\t0\t100",
        "B00002\tB00002\t1.0\t1.0\t1.0\t0\t100",
    ]


def _write_tsv(path: Path, rows: list[str], *, header: str = HEADER) -> Path:
    path.write_text(
        "\n".join((header, *rows)) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_parse_pair_tsv_normalizes_reciprocals_and_keeps_best_row(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import (
        CandidateIndex,
        SequenceNode,
        SimilarityEdge,
        parse_pair_tsv,
    )

    first, second = _nodes()
    assert isinstance(first, SequenceNode)
    assert isinstance(second, SequenceNode)
    expected = CandidateIndex.from_nodes((first, second))
    pair_tsv = tmp_path / "pairs.tsv"
    _write_tsv(
        pair_tsv,
        [
            *_self_rows(),
            "A00001\tB00002\t0.55\t0.90\t0.85\t1e-8\t80",
            "B00002\tA00001\t0.60\t0.82\t0.95\t1e-6\t70",
        ],
    )

    edges = parse_pair_tsv(pair_tsv, expected)

    assert edges == (
        SimilarityEdge(
            left=first,
            right=second,
            query_accession="B00002",
            target_accession="A00001",
            fident=Decimal("0.60"),
            qcov=Decimal("0.82"),
            tcov=Decimal("0.95"),
            evalue=Decimal("1e-6"),
            bits=Decimal("70"),
        ),
    )


@pytest.mark.parametrize(
    "header",
    [
        "query\ttarget\tfident\tqcov\ttcov\tevalue",
        f"{HEADER}\textra",
        "target\tquery\tfident\tqcov\ttcov\tevalue\tbits",
        "query,target,fident,qcov,tcov,evalue,bits",
    ],
)
def test_parse_pair_tsv_requires_exact_header(tmp_path: Path, header: str) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(tmp_path / "bad-header.tsv", _self_rows(), header=header)

    with pytest.raises(RuntimeError, match="header"):
        parse_pair_tsv(path, _index())


def test_parse_pair_tsv_rejects_repeated_header(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(tmp_path / "repeated-header.tsv", [*_self_rows(), HEADER])

    with pytest.raises(RuntimeError, match="header"):
        parse_pair_tsv(path, _index())


@pytest.mark.parametrize("field_count", [6, 8])
def test_parse_pair_tsv_rejects_wrong_field_count(tmp_path: Path, field_count: int) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    fields = ["A00001", "B00002", "0.5", "0.9", "0.9", "1e-8", "80"]
    if field_count == 6:
        fields.pop()
    else:
        fields.append("extra")
    path = _write_tsv(tmp_path / "wrong-fields.tsv", [*_self_rows(), "\t".join(fields)])

    with pytest.raises(RuntimeError, match="seven fields"):
        parse_pair_tsv(path, _index())


@pytest.mark.parametrize("value", ["not-a-number", "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field_index", [2, 3, 4, 5, 6])
def test_parse_pair_tsv_rejects_malformed_or_nonfinite_numeric_values(
    tmp_path: Path,
    field_index: int,
    value: str,
) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    fields = ["A00001", "B00002", "0.5", "0.9", "0.9", "1e-8", "80"]
    fields[field_index] = value
    path = _write_tsv(tmp_path / "bad-number.tsv", [*_self_rows(), "\t".join(fields)])

    with pytest.raises(RuntimeError, match="numeric"):
        parse_pair_tsv(path, _index())


@pytest.mark.parametrize(
    ("field_index", "value"),
    [
        (2, "-0.01"),
        (2, "1.01"),
        (3, "-0.01"),
        (3, "1.01"),
        (4, "-0.01"),
        (4, "1.01"),
        (5, "-0.01"),
        (6, "-0.01"),
    ],
)
def test_parse_pair_tsv_rejects_values_outside_numeric_ranges(
    tmp_path: Path,
    field_index: int,
    value: str,
) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    fields = ["A00001", "B00002", "0.5", "0.9", "0.9", "1e-8", "80"]
    fields[field_index] = value
    path = _write_tsv(tmp_path / "bad-range.tsv", [*_self_rows(), "\t".join(fields)])

    with pytest.raises(RuntimeError, match="range"):
        parse_pair_tsv(path, _index())


def test_parse_pair_tsv_rejects_unknown_identifier(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(
        tmp_path / "unknown.tsv",
        [*_self_rows(), "UNKNOWN\tA00001\t0.5\t0.9\t0.9\t1e-8\t80"],
    )

    with pytest.raises(RuntimeError, match="unknown"):
        parse_pair_tsv(path, _index())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        ((HEADER + "\n").encode(), "hit"),
        ((HEADER + "\r\n").encode(), "LF"),
        ((HEADER + "\n" + _self_rows()[0]).encode(), "LF"),
        (b"\xff\n", "UTF-8"),
    ],
)
def test_parse_pair_tsv_requires_strict_utf8_lf_nonempty_self_search(
    tmp_path: Path,
    content: bytes,
    message: str,
) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = tmp_path / "strict.tsv"
    path.write_bytes(content)

    with pytest.raises(RuntimeError, match=message):
        parse_pair_tsv(path, _index())


def test_parse_pair_tsv_reports_missing_file(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    with pytest.raises(RuntimeError, match="not found"):
        parse_pair_tsv(tmp_path / "missing.tsv", _index())


def test_parse_pair_tsv_requires_qualifying_self_hit_for_every_node(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(
        tmp_path / "missing-self.tsv",
        [
            _self_rows()[0],
            "A00001\tB00002\t0.6\t0.9\t0.9\t1e-8\t80",
        ],
    )

    with pytest.raises(RuntimeError, match="self hit"):
        parse_pair_tsv(path, _index())


def test_parse_pair_tsv_rejects_nonqualifying_self_hit(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(
        tmp_path / "bad-self.tsv",
        [
            "A00001\tA00001\t1.0\t0.79\t1.0\t0\t100",
            _self_rows()[1],
        ],
    )

    with pytest.raises(RuntimeError, match="self hit"):
        parse_pair_tsv(path, _index())


def test_parse_pair_tsv_filters_nonqualifying_nonself_hits(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(
        tmp_path / "filtered.tsv",
        [
            *_self_rows(),
            "A00001\tB00002\t0.9\t0.79\t1.0\t1e-8\t90",
            "B00002\tA00001\t0.9\t1.0\t1.0\t0.0011\t90",
        ],
    )

    assert parse_pair_tsv(path, _index()) == ()


def test_parse_pair_tsv_deduplicates_exact_rows(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    row = "A00001\tB00002\t0.6\t0.9\t0.9\t1e-8\t80"
    path = _write_tsv(tmp_path / "duplicates.tsv", [*_self_rows(), row, row])

    assert len(parse_pair_tsv(path, _index())) == 1


def test_parse_pair_tsv_applies_complete_best_hit_order(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    path = _write_tsv(
        tmp_path / "best.tsv",
        [
            *_self_rows(),
            "B00002\tA00001\t0.59\t0.99\t0.99\t1e-12\t999",
            "B00002\tA00001\t0.60\t0.81\t0.99\t1e-12\t999",
            "B00002\tA00001\t0.60\t0.82\t0.99\t1e-12\t70",
            "B00002\tA00001\t0.60\t0.82\t0.99\t1e-6\t80",
            "B00002\tA00001\t0.60\t0.82\t0.99\t1e-7\t80",
            "A00001\tB00002\t0.60\t0.82\t0.99\t1e-7\t80",
        ],
    )

    edge = parse_pair_tsv(path, _index())[0]

    assert edge.query_accession == "A00001"
    assert edge.target_accession == "B00002"
    assert edge.fident == Decimal("0.60")
    assert min(edge.qcov, edge.tcov) == Decimal("0.82")
    assert edge.bits == Decimal("80")
    assert edge.evalue == Decimal("1e-7")


def test_parse_pair_tsv_is_stable_when_fully_ranked_rows_tie(tmp_path: Path) -> None:
    from protein_split_audit.similarity.parse_clusters import parse_pair_tsv

    rows = [
        *_self_rows(),
        "A00001\tB00002\t0.60\t0.82\t0.95\t1e-7\t80",
        "A00001\tB00002\t0.60\t0.95\t0.82\t1e-7\t80",
    ]
    forward = _write_tsv(tmp_path / "forward.tsv", rows)
    reverse = _write_tsv(tmp_path / "reverse.tsv", list(reversed(rows)))

    assert parse_pair_tsv(forward, _index()) == parse_pair_tsv(reverse, _index())


@pytest.mark.parametrize(
    "nodes",
    [
        (),
        (
            ("A00001", "a" * 64),
            ("A00001", "b" * 64),
        ),
        (
            ("A00001", "a" * 64),
            ("B00002", "a" * 64),
        ),
    ],
)
def test_candidate_index_rejects_empty_or_duplicate_identities(
    nodes: tuple[tuple[str, str], ...],
) -> None:
    from protein_split_audit.similarity.parse_clusters import (
        CandidateIndex,
        SequenceNode,
    )

    values = tuple(
        SequenceNode(accession=accession, sequence_sha256=digest) for accession, digest in nodes
    )

    with pytest.raises(ValueError, match="candidate index"):
        CandidateIndex.from_nodes(values)


@pytest.mark.parametrize(
    ("accession", "digest"),
    [
        ("", "a" * 64),
        ("A00001", "A" * 64),
        ("A00001", "not-a-sha256"),
    ],
)
def test_sequence_node_rejects_invalid_identity(accession: str, digest: str) -> None:
    from protein_split_audit.similarity.parse_clusters import SequenceNode

    with pytest.raises(ValueError, match="sequence node"):
        SequenceNode(accession=accession, sequence_sha256=digest)
