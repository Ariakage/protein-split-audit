# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

from protein_split_audit.experiments.replay import compare_test_replays
from tests.test_test_replay import _formal_pair


def test_wrong_session_order_or_consumed_ledger_blocks_replay(tmp_path: Path) -> None:
    first, second = _formal_pair(tmp_path)
    ledger = tmp_path / "access-ledger/run-b.jsonl"
    events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    events[0]["session_id"] = "run-a"
    ledger.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    report = compare_test_replays(first, second, tmp_path / "ledger-mismatch.json")

    assert report.release_eligible is False
    assert "access-ledger" in " ".join(report.mismatches)
