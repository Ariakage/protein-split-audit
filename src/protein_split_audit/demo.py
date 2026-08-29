# SPDX-License-Identifier: Apache-2.0

"""Deterministic, offline, aggregate-only demonstration workflow."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from protein_split_audit import __version__
from protein_split_audit.evaluation.metrics import EvaluationMetrics, evaluate_predictions
from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.features.amino_acid_composition import extract_aac
from protein_split_audit.features.schemas import FeatureConfig, FeaturePreprocessing
from protein_split_audit.features.validation import SequenceRecord
from protein_split_audit.models.logistic_regression import train_logistic
from protein_split_audit.models.schemas import LogisticRegressionModelConfig
from protein_split_audit.provenance import sha256_bytes
from protein_split_audit.publication import PublicationError, publish_bundle
from protein_split_audit.similarity.connected_components import (
    ComponentPartition,
    build_components,
)
from protein_split_audit.similarity.parse_clusters import SequenceNode, SimilarityEdge
from protein_split_audit.splits.grouped_split import create_grouped_split
from protein_split_audit.splits.random_split import (
    SplitAssignment,
    SplitMember,
    create_random_split,
)

_LABELS = ("1.1", "2.7", "3.1")
_CLASS_ALPHABETS = ("ACDEFG", "HIKLMN", "PQRSTVWY")
_SEED = 42
_COMPONENTS_PER_CLASS = 15
_MEMBERS_PER_COMPONENT = 2
_SEQUENCE_LENGTH = 120


class DemoError(RuntimeError):
    """Raised when the public synthetic demonstration cannot be produced safely."""


@dataclass(frozen=True, slots=True)
class DemoSplitSummary:
    """Aggregate-only outcome for one synthetic split strategy."""

    strategy: str
    train_count: int
    validation_count: int
    test_count: int
    component_crossings: int
    macro_f1: float
    balanced_accuracy: float
    accuracy: float


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Deterministic aggregate result returned to API callers."""

    sequence_count: int
    class_count: int
    component_count: int
    splits: tuple[DemoSplitSummary, ...]


@dataclass(frozen=True, slots=True)
class _SyntheticRow:
    member: SplitMember
    node: SequenceNode
    sequence: str


def _deterministic_bytes(token: str, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hashlib.sha256(f"{token}\n{counter}".encode()).digest())
        counter += 1
    return bytes(output[:length])


def _base_sequence(label_index: int, component_index: int) -> str:
    alphabet = _CLASS_ALPHABETS[label_index]
    values = _deterministic_bytes(
        f"class-{label_index}-component-{component_index}",
        _SEQUENCE_LENGTH,
    )
    return "".join(alphabet[value % len(alphabet)] for value in values)


def _paired_sequence(base: str, label_index: int, component_index: int) -> str:
    alphabet = _CLASS_ALPHABETS[label_index]
    sequence = list(base)
    offset = component_index % 10
    for position in range(offset, len(sequence), 10):
        current = alphabet.index(sequence[position])
        sequence[position] = alphabet[(current + 1) % len(alphabet)]
    return "".join(sequence)


def _synthetic_cohort() -> tuple[tuple[_SyntheticRow, ...], ComponentPartition]:
    rows: list[_SyntheticRow] = []
    edges: list[SimilarityEdge] = []
    for label_index, label in enumerate(_LABELS):
        for component_index in range(_COMPONENTS_PER_CLASS):
            base = _base_sequence(label_index, component_index)
            sequences = (base, _paired_sequence(base, label_index, component_index))
            component_nodes: list[SequenceNode] = []
            for member_index, sequence in enumerate(sequences, start=1):
                identity = sha256_bytes(sequence.encode("ascii"))
                public_id = f"SYN-C{label_index + 1:02d}-G{component_index + 1:02d}-M{member_index}"
                member = SplitMember(public_id, identity, label)
                node = SequenceNode(public_id, identity)
                rows.append(_SyntheticRow(member=member, node=node, sequence=sequence))
                component_nodes.append(node)
            left, right = component_nodes
            edges.append(
                SimilarityEdge(
                    left=left,
                    right=right,
                    query_accession=left.accession,
                    target_accession=right.accession,
                    fident=Decimal("0.90"),
                    qcov=Decimal("1.00"),
                    tcov=Decimal("1.00"),
                    evalue=Decimal("0"),
                    bits=Decimal("120"),
                )
            )
    nodes = tuple(row.node for row in rows)
    return tuple(rows), build_components(nodes, edges, Decimal("0.30"))


def _component_crossings(
    assignment: SplitAssignment,
    components: ComponentPartition,
) -> int:
    split_by_public_id = {row.accession: row.split for row in assignment.rows}
    splits_by_component: dict[str, set[str]] = {}
    for row in components.rows:
        splits_by_component.setdefault(row.component_id, set()).add(
            split_by_public_id[row.node.accession]
        )
    return sum(len(splits) > 1 for splits in splits_by_component.values())


def _feature_config() -> FeatureConfig:
    return FeatureConfig(
        schema_version=1,
        name="aac",
        kind="aac",
        implementation_version="aac20-v1",
        feature_count=20,
        dtype="float64",
        normalization="sequence_length",
        preprocessing=FeaturePreprocessing(scaler="standard_train_only"),
    )


def _model_config() -> LogisticRegressionModelConfig:
    return LogisticRegressionModelConfig.model_validate(
        {
            "schema_version": 1,
            "type": "logistic_regression",
            "solver": "lbfgs",
            "penalty": "l2",
            "C": 1.0,
            "class_weight": "balanced",
            "max_iter": 5000,
            "tol": 0.0001,
            "fit_intercept": True,
            "random_state": 42,
        }
    )


def _evaluate_split(
    assignment: SplitAssignment,
    synthetic_rows: tuple[_SyntheticRow, ...],
) -> EvaluationMetrics:
    sequence_by_id = {row.member.accession: row.sequence for row in synthetic_rows}
    records = tuple(
        SequenceRecord(
            accession=row.accession,
            sequence_sha256=bytes.fromhex(row.sequence_sha256),
            label=row.ec_level_2,
            split=row.split,
            sequence=sequence_by_id[row.accession],
        )
        for row in assignment.rows
    )
    matrix = extract_aac(records)
    model = train_logistic(matrix, records, _LABELS, _feature_config(), _model_config())
    test_indices = [index for index, record in enumerate(records) if record.split == "test"]
    test_matrix = matrix[test_indices]
    predictions = model.predict(test_matrix)
    probabilities = model.predict_proba(test_matrix)
    prediction_rows = tuple(
        PredictionRow(
            accession=records[index].accession,
            sequence_sha256=records[index].sequence_sha256,
            split_name=assignment.name,
            true_label=records[index].label,
            predicted_label=predictions[position],
            scores=tuple(float(value) for value in probabilities[position]),
            nearest_train_identity=None,
            no_hit=None,
            evaluation_split="test",
        )
        for position, index in enumerate(test_indices)
    )
    return evaluate_predictions(prediction_rows, _LABELS)


def _summarize(
    assignment: SplitAssignment,
    components: ComponentPartition,
    metrics: EvaluationMetrics,
) -> DemoSplitSummary:
    return DemoSplitSummary(
        strategy=assignment.name,
        train_count=assignment.counts["train"],
        validation_count=assignment.counts["validation"],
        test_count=assignment.counts["test"],
        component_crossings=_component_crossings(assignment, components),
        macro_f1=round(metrics.macro_f1, 12),
        balanced_accuracy=round(metrics.balanced_accuracy, 12),
        accuracy=round(metrics.accuracy, 12),
    )


def _csv_bytes(summaries: tuple[DemoSplitSummary, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        (
            "split_strategy",
            "train_count",
            "validation_count",
            "test_count",
            "component_crossings",
            "macro_f1",
            "balanced_accuracy",
            "accuracy",
        )
    )
    for summary in summaries:
        writer.writerow(
            (
                summary.strategy,
                summary.train_count,
                summary.validation_count,
                summary.test_count,
                summary.component_crossings,
                f"{summary.macro_f1:.6f}",
                f"{summary.balanced_accuracy:.6f}",
                f"{summary.accuracy:.6f}",
            )
        )
    return stream.getvalue().encode("utf-8")


def _readme_bytes() -> bytes:
    return (
        b"# ProteinSplitAudit synthetic methods demo\n\n"
        b"This bundle is a deterministic software smoke test built from generated protein-like "
        b"records. It exercises strict similarity components, Random and Cluster30 splitting, "
        b"train-only AAC extraction, a fixed logistic-regression baseline, and aggregate "
        b"evaluation.\n\n"
        b"The values in this directory are not biological observations, benchmark results, or "
        b"evidence for scientific claims. Real similarity workflows use the separately recorded "
        b"MMseqs2 protocol.\n"
    )


def _manifest_bytes(
    result: DemoResult,
    readme: bytes,
    summary_csv: bytes,
) -> bytes:
    specification = {
        "class_alphabets": list(_CLASS_ALPHABETS),
        "components_per_class": _COMPONENTS_PER_CLASS,
        "members_per_component": _MEMBERS_PER_COMPONENT,
        "seed": _SEED,
        "sequence_length": _SEQUENCE_LENGTH,
        "similarity_identity": "0.90",
        "similarity_threshold": "0.30",
    }
    specification_bytes = json.dumps(specification, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    payload = {
        "artifact_kind": "synthetic_methods_demo",
        "dataset": {
            "class_count": result.class_count,
            "component_count": result.component_count,
            "sequence_count": result.sequence_count,
        },
        "evidence_scope": "software_smoke_test_only",
        "files": {
            "README.md": sha256_bytes(readme),
            "split_summary.csv": sha256_bytes(summary_csv),
        },
        "schema_version": 1,
        "software_version": __version__,
        "specification_sha256": sha256_bytes(specification_bytes),
        "splits": {
            summary.strategy: {
                key: value for key, value in asdict(summary).items() if key != "strategy"
            }
            for summary in result.splits
        },
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def run_synthetic_demo(output_dir: Path) -> DemoResult:
    """Run the offline synthetic workflow and publish three aggregate-only files."""

    synthetic_rows, components = _synthetic_cohort()
    cohort = tuple(row.member for row in synthetic_rows)
    random_assignment = create_random_split(cohort, seed=_SEED)
    grouped_assignment = create_grouped_split(
        cohort,
        components,
        name="cluster30",
        seed=_SEED,
    )
    summaries = tuple(
        _summarize(assignment, components, _evaluate_split(assignment, synthetic_rows))
        for assignment in (random_assignment, grouped_assignment)
    )
    result = DemoResult(
        sequence_count=len(synthetic_rows),
        class_count=len(_LABELS),
        component_count=len({row.component_id for row in components.rows}),
        splits=summaries,
    )
    readme = _readme_bytes()
    summary_csv = _csv_bytes(summaries)
    manifest = _manifest_bytes(result, readme, summary_csv)
    try:
        publish_bundle(
            {
                output_dir / "README.md": readme,
                output_dir / "split_summary.csv": summary_csv,
                output_dir / "demo_manifest.json": manifest,
            }
        )
    except PublicationError as error:
        raise DemoError(str(error)) from error
    return result


__all__ = ["DemoError", "DemoResult", "DemoSplitSummary", "run_synthetic_demo"]
