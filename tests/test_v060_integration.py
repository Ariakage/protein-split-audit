# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from protein_split_audit.analysis.aggregate import (
    CSV_SCHEMAS,
    build_analysis_outputs,
    write_deterministic_bundle,
    write_review_aggregate,
)
from protein_split_audit.analysis.inputs import AnalysisRow
from protein_split_audit.analysis.privacy import validate_v060_release_bundle
from protein_split_audit.analysis.replay import compare_analysis_replays
from protein_split_audit.analysis.schemas import METHODS, SPLITS
from protein_split_audit.provenance import sha256_file
from protein_split_audit.reporting.figures import render_release_figures
from tests.v060_analysis_helpers import LABELS


def _rows() -> tuple[AnalysisRow, ...]:
    output: list[AnalysisRow] = []
    for split in SPLITS:
        metadata = tuple(
            AnalysisRow(
                accession=f"SYNTH{index:03d}",
                sequence_sha256=index.to_bytes(32, "big"),
                split_name=split,
                method="nearest-homolog",
                true_label=LABELS[index],
                predicted_label=LABELS[index],
                correct=True,
                sequence_length=100 + index * 200,
                component_id=f"component-{index}",
                component_size=index + 1,
                nearest_train_identity=0.35,
                no_hit=False,
                nearest_train_accession=f"TRAIN{index:03d}",
                nearest_train_label=LABELS[index],
                query_coverage=0.9,
                target_coverage=0.9,
                bitscore=100.0 + index,
                evalue=1e-8,
            )
            for index in range(5)
        )
        for method_order, method in enumerate(METHODS):
            for row in metadata:
                predicted = (
                    row.true_label
                    if method == "nearest-homolog" or method_order % 2 == 0
                    else LABELS[(LABELS.index(row.true_label) + 1) % len(LABELS)]
                )
                output.append(
                    replace(
                        row,
                        method=method,
                        predicted_label=predicted,
                        correct=predicted == row.true_label,
                    )
                )
    return tuple(output)


def test_synthetic_rows_replay_aggregate_figures_and_privacy(tmp_path: Path) -> None:
    attestation = tmp_path / "synthetic-attestation.yaml"
    attestation.write_text("schema_version: 1\n", encoding="utf-8")
    outputs = build_analysis_outputs(
        _rows(),
        manifest_context={"attestation_sha256": sha256_file(attestation)},
        strict_row_count=False,
    )
    assert set(outputs) == {*CSV_SCHEMAS, "analysis_manifest.json"}
    first = tmp_path / "analysis-a"
    second = tmp_path / "analysis-b"
    write_deterministic_bundle(first, outputs)
    write_deterministic_bundle(second, outputs)
    (first / "run_provenance.json").write_text('{"session":"a"}\n', encoding="utf-8")
    (second / "run_provenance.json").write_text('{"session":"b"}\n', encoding="utf-8")
    replay = compare_analysis_replays(first, second, tmp_path / "replay.json")

    review = tmp_path / "review"
    write_review_aggregate(first, replay.report_path, attestation, review)
    render_release_figures(review, review / "figures")
    validate_v060_release_bundle(review)
