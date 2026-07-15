# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from protein_split_audit.splits.random_split import SplitMember, create_random_split


def test_serialize_split_assignment_is_deterministic_and_explicit() -> None:
    from protein_split_audit.splits.artifacts import SPLIT_MANIFEST_SCHEMA, serialize_split

    members = tuple(SplitMember(f"P{index:02d}", f"{index:064x}", "1.1") for index in range(1, 21))
    split = create_random_split(members, seed=42)

    first = serialize_split(split)
    second = serialize_split(split)

    assert first == second
    table = pq.read_table(pa.BufferReader(first.parquet_bytes))
    assert table.schema.equals(SPLIT_MANIFEST_SCHEMA, check_metadata=False)
    assert table.num_rows == 20
    assert first.file_sha256 != first.semantic_sha256
