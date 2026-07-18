# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.analysis.inputs import AnalysisRow
from protein_split_audit.analysis.schemas import MethodName, SplitName

LABELS = ("2.7", "3.1", "1.1", "2.1", "4.1")


def synthetic_rows(
    count: int,
    *,
    method: MethodName = "esm2-150m",
    split: SplitName = "random",
    component_count: int | None = None,
    identity: float | None = 0.35,
    no_hit: bool = False,
    length: int = 250,
    correct_every: int = 2,
) -> tuple[AnalysisRow, ...]:
    components = component_count if component_count is not None else count
    rows: list[AnalysisRow] = []
    for index in range(count):
        true_label = LABELS[index % len(LABELS)]
        predicted = true_label if index % correct_every == 0 else LABELS[(index + 1) % len(LABELS)]
        rows.append(
            AnalysisRow(
                accession=f"SYN{index:05d}",
                sequence_sha256=index.to_bytes(32, "big"),
                split_name=split,
                method=method,
                true_label=true_label,
                predicted_label=predicted,
                correct=true_label == predicted,
                sequence_length=length,
                component_id=f"component-{index % components:03d}",
                component_size=1 + index % 25,
                nearest_train_identity=None if no_hit else identity,
                no_hit=no_hit,
            )
        )
    return tuple(rows)
