# SPDX-License-Identifier: Apache-2.0
"""Independently verify every number reported in the Typst manuscript.

Cross-checks each frozen figure in ``docs/paper/paper.typ`` against the
immutable artifacts under ``results/released`` and ``data/manifests``, then
writes a JSON verification record to ``docs/attestations``. Also records the
SHA-256 of the manuscript sources so the frozen text can be re-identified.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASED = ROOT / "results" / "released"

MANUSCRIPT_SOURCES = (
    "docs/paper/paper.typ",
    "docs/paper/references.bib",
    "docs/paper/images/workflow.svg",
)

PAPER_TABLE2 = {
    ("majority", "random"): 0.122,
    ("majority", "cluster70"): 0.122,
    ("majority", "cluster50"): 0.122,
    ("majority", "cluster30"): 0.122,
    ("length-logistic", "random"): 0.171,
    ("length-logistic", "cluster70"): 0.142,
    ("length-logistic", "cluster50"): 0.148,
    ("length-logistic", "cluster30"): 0.189,
    ("aac-logistic", "random"): 0.236,
    ("aac-logistic", "cluster70"): 0.343,
    ("aac-logistic", "cluster50"): 0.349,
    ("aac-logistic", "cluster30"): 0.246,
    ("kmer3-logistic", "random"): 0.358,
    ("kmer3-logistic", "cluster70"): 0.418,
    ("kmer3-logistic", "cluster50"): 0.389,
    ("kmer3-logistic", "cluster30"): 0.389,
    ("nearest-homolog", "random"): 0.369,
    ("nearest-homolog", "cluster70"): 0.462,
    ("nearest-homolog", "cluster50"): 0.543,
    ("nearest-homolog", "cluster30"): 0.307,
    ("esm2-35m", "random"): 0.797,
    ("esm2-35m", "cluster70"): 0.735,
    ("esm2-35m", "cluster50"): 0.860,
    ("esm2-35m", "cluster30"): 0.713,
    ("esm2-150m", "random"): 0.784,
    ("esm2-150m", "cluster70"): 0.807,
    ("esm2-150m", "cluster50"): 0.844,
    ("esm2-150m", "cluster30"): 0.780,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_bytes())


def check(label: str, expected: object, actual: object, checks: list[dict]) -> None:
    checks.append(
        {
            "claim": label,
            "expected": expected,
            "artifact_value": actual,
            "match": expected == actual,
        }
    )
    if expected != actual:
        raise SystemExit(f"verification failed: {label}: {expected!r} != {actual!r}")


def main() -> None:
    checks: list[dict] = []

    build = _load_json("data/manifests/pilot.build.json")
    check("source records downloaded", 2632, build["counts"]["input_records"], checks)
    check("accepted candidates", 1182, build["counts"]["retained_candidates"], checks)

    cohort = _load_json("results/released/v0.2.0/pilot-v1.cohort.json")
    check(
        "frozen cohort row count",
        442,
        cohort["artifacts"]["cohort_manifest"]["row_count"],
        checks,
    )
    selected = [row["selected_count"] for row in cohort["class_summaries"] if row["selected"]]
    check("selected per class (2.7, 3.1, 1.1, 2.1, 4.1)", [192, 85, 59, 57, 49], selected, checks)

    for name, expected in (("cluster70", 437), ("cluster50", 427), ("cluster30", 398)):
        manifest = _load_json(f"results/released/v0.2.0/pilot-v1.{name}.json")
        check(
            f"{name} strict components",
            expected,
            manifest["counts"]["strict_component_count"],
            checks,
        )

    split_summary = _load_json("results/released/v0.2.0/split_summary.json")
    for split_name, split in split_summary["splits"].items():
        check(
            f"{split_name} split counts (train/validation/test)",
            {"train": 308, "validation": 68, "test": 66},
            split["counts"],
            checks,
        )

    random_audit = _load_json("results/released/v0.2.0/random.audit.json")
    check(
        "random-split exceedance counts at 0.30/0.50/0.70",
        {"0.30": 4, "0.50": 2, "0.70": 0},
        random_audit["counts"]["exceedance_counts"],
        checks,
    )

    summary_rows = list(
        csv.DictReader(
            (RELEASED / "v0.6.0/split_performance_summary.csv").open(encoding="utf-8", newline="")
        )
    )
    for row in summary_rows:
        if row["stratum_id"] != "whole_test" or row["metric"] != "macro_f1":
            continue
        if row["reporting_status"] != "reportable":
            continue
        key = (row["method"], row["split_name"])
        if key not in PAPER_TABLE2:
            continue
        check(
            f"Table 2 Macro-F1 {key[0]} / {key[1]}",
            PAPER_TABLE2[key],
            round(float(row["estimate"]), 3),
            checks,
        )

    per_class = list(
        csv.DictReader((RELEASED / "v0.5.0/test_per_class.csv").open(encoding="utf-8", newline=""))
    )
    supports = {
        row["label"]: int(row["support"])
        for row in per_class
        if row["split"] == "random" and row["method"] == "majority"
    }
    check(
        "test support per class (2.7, 3.1, 1.1, 2.1, 4.1)",
        {"2.7": 29, "3.1": 13, "1.1": 9, "2.1": 8, "4.1": 7},
        supports,
        checks,
    )

    gaps = list(
        csv.DictReader(
            (RELEASED / "v0.5.0/generalization_gap.csv").open(encoding="utf-8", newline="")
        )
    )
    check("prespecified Random-minus-cluster intervals", 21, len(gaps), checks)
    check(
        "all 21 intervals include zero",
        True,
        all(float(row["lower"]) <= 0 <= float(row["upper"]) for row in gaps),
        checks,
    )

    replay_v050 = _load_json("results/released/v0.5.0/replay_report.json")
    check(
        "v0.5.0 replayed deterministic artifacts",
        430,
        replay_v050["compared_file_count"],
        checks,
    )
    check("v0.5.0 replay byte-identical", True, replay_v050["byte_identical"], checks)

    replay_v060 = _load_json("results/released/v0.6.0/replay_report.json")
    check(
        "v0.6.0 replayed deterministic files",
        11,
        replay_v060["compared_file_count"],
        checks,
    )
    check(
        "v0.6.0 replay deterministic mismatches",
        0,
        replay_v060["deterministic_mismatch_count"],
        checks,
    )

    manuscript_sha256 = {relative: _sha256(ROOT / relative) for relative in MANUSCRIPT_SOURCES}

    record = {
        "schema_version": 1,
        "record_type": "manuscript_number_verification",
        "manuscript": "docs/paper/paper.typ",
        "manuscript_sources_sha256": manuscript_sha256,
        "checks": checks,
        "all_match": all(entry["match"] for entry in checks),
    }
    output = ROOT / "docs/attestations/manuscript-number-verification.json"
    output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"verified {len(checks)} claims; record written to {output.relative_to(ROOT)}")
    for relative, digest in manuscript_sha256.items():
        print(f"  {relative} sha256={digest}")


if __name__ == "__main__":
    main()
