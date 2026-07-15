# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from protein_split_audit.similarity.parse_clusters import CandidateIndex, SequenceNode


def _indexes() -> tuple[CandidateIndex, CandidateIndex]:
    test = CandidateIndex.from_nodes(
        (
            SequenceNode("TEST1", "a" * 64),
            SequenceNode("TEST2", "b" * 64),
        )
    )
    train = CandidateIndex.from_nodes(
        (
            SequenceNode("TRAIN1", "c" * 64),
            SequenceNode("TRAIN2", "d" * 64),
        )
    )
    return test, train


def test_parse_search_tsv_allows_empty_output_and_selects_no_match(tmp_path: Path) -> None:
    from protein_split_audit.similarity.audit_train_test import (
        parse_search_tsv,
        select_nearest_train,
    )

    test, train = _indexes()
    path = tmp_path / "empty.tsv"
    path.write_bytes(b"")

    assert parse_search_tsv(path, test, train) == ()
    nearest = select_nearest_train(test, ())
    assert [row.no_match for row in nearest] == [True, True]
    assert [row.train_accession for row in nearest] == [None, None]


def test_nearest_train_tie_break_and_all_hit_violation_scan(tmp_path: Path) -> None:
    from protein_split_audit.similarity.audit_train_test import (
        audit_observed_hits,
        parse_search_tsv,
        select_nearest_train,
    )

    test, train = _indexes()
    path = tmp_path / "hits.tsv"
    path.write_text(
        "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits\n"
        "TEST1\tTRAIN2\t0.70\t0.90\t0.90\t1e-20\t100\n"
        "TEST1\tTRAIN1\t0.70\t0.90\t0.90\t1e-20\t100\n"
        "TEST2\tTRAIN2\t0.50\t0.90\t0.90\t1e-10\t80\n",
        encoding="utf-8",
        newline="\n",
    )
    hits = parse_search_tsv(path, test, train)
    nearest = select_nearest_train(test, hits)

    assert nearest[0].train_accession == "TRAIN1"
    descriptive = audit_observed_hits(
        nearest,
        hits,
        test_labels={"TEST1": "1.1", "TEST2": "2.7"},
        train_labels={"TRAIN1": "1.1", "TRAIN2": "3.1"},
        strategy="random_control",
        violation_identity_threshold=None,
    )
    assert descriptive.release_eligible
    assert descriptive.violation_count == 0

    with pytest.raises(RuntimeError, match="violation"):
        audit_observed_hits(
            nearest,
            hits,
            test_labels={"TEST1": "1.1", "TEST2": "2.7"},
            train_labels={"TRAIN1": "1.1", "TRAIN2": "3.1"},
            strategy="similarity_component",
            violation_identity_threshold=Decimal("0.70"),
        )


def test_search_parser_rejects_unknown_and_malformed_rows(tmp_path: Path) -> None:
    from protein_split_audit.similarity.audit_train_test import parse_search_tsv

    test, train = _indexes()
    path = tmp_path / "bad.tsv"
    path.write_text(
        "query\ttarget\tfident\tqcov\ttcov\tevalue\tbits\n"
        "UNKNOWN\tTRAIN1\t0.5\t0.9\t0.9\t1e-5\t50\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(RuntimeError, match="unknown"):
        parse_search_tsv(path, test, train)
