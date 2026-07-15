# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path


def test_replay_report_excludes_run_specific_provenance(tmp_path: Path) -> None:
    from protein_split_audit.experiments.replay import compare_validation_replays

    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, elapsed in ((first, 1.0), (second, 2.0)):
        cell = root / "experiment__random__majority__seed42__abc"
        cell.mkdir(parents=True)
        (cell / "metrics.json").write_text('{"macro_f1":0.2}\n', encoding="utf-8")
        (cell / "resource_usage.json").write_text(
            json.dumps({"elapsed": elapsed}) + "\n", encoding="utf-8"
        )
        (cell / "environment.json").write_text(
            json.dumps({"host": root.name}) + "\n", encoding="utf-8"
        )
        (cell / "COMPLETE.json").write_text("{}\n", encoding="utf-8")
        (root / "matrix_summary.json").write_text('{"cell_count":1}\n', encoding="utf-8")

    output = tmp_path / "report.json"
    report = compare_validation_replays(first, second, output)

    assert report.byte_identical is True
    assert report.compared_file_count == 2
    assert json.loads(output.read_text(encoding="utf-8"))["excluded_run_specific"] == [
        "COMPLETE.json",
        "environment.json",
        "resource_usage.json",
        "run.log",
    ]
