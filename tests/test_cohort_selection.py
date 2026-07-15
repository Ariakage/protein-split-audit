# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from protein_split_audit.cohort.schemas import (
    CandidatePool,
    CandidateRecord,
    CohortFeasibilityConfig,
    CohortSelectionConfig,
)
from protein_split_audit.provenance import BuildCounts, BuildManifest, GitMetadata, sha256_bytes
from protein_split_audit.similarity.connected_components import ComponentPartition, build_components
from protein_split_audit.similarity.parse_clusters import SequenceNode, SimilarityEdge

_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
_RULE_VERSION = "pilot-ec2-5class-min40-c30g10-cap250-seed42-v1"
_PROJECT_ROOT = Path(__file__).parents[1]


def _sequence(index: int) -> str:
    suffix: list[str] = []
    value = index
    for _ in range(5):
        suffix.append(_ALPHABET[value % len(_ALPHABET)])
        value //= len(_ALPHABET)
    return "A" * 45 + "".join(reversed(suffix))


def _record(label: str, index: int) -> CandidateRecord:
    sequence = _sequence(index)
    accession = f"P{index:06d}"
    return CandidateRecord(
        accession=accession,
        entry_name=f"ENTRY_{index}",
        protein_name=f"Synthetic enzyme {index}",
        organism_name="Synthetic organism",
        organism_id=83333,
        sequence=sequence,
        sequence_length=len(sequence),
        sequence_sha256=sha256_bytes(sequence.encode("ascii")),
        ec_number=f"{label}.1.1",
        ec_level_2=label,
        duplicate_count=1,
        duplicate_accessions=(accession,),
        source_page_number=1,
        source_row_number=index + 1,
    )


def _build_manifest(record_count: int) -> BuildManifest:
    return BuildManifest(
        built_at_utc=datetime(2026, 7, 15, tzinfo=UTC),
        parent_download_manifest="data/manifests/source.download.json",
        source_manifest_sha256="1" * 64,
        configuration_file="configs/dataset/pilot.yaml",
        configuration_sha256="2" * 64,
        input_file="data/raw/source.tsv.gz",
        input_file_sha256="3" * 64,
        input_normalized_content_sha256="4" * 64,
        output_file_sha256={"pilot.parquet": "5" * 64, "pilot.fasta": "6" * 64},
        counts=BuildCounts(
            input_records=record_count,
            after_ec_filter=record_count,
            after_sequence_filter=record_count,
            after_conflict_filter=record_count,
            retained_candidates=record_count,
        ),
        rejection_reason_counts={},
        duplicate_group_count=0,
        duplicate_alias_count=0,
        conflict_group_count=0,
        conflicting_record_count=0,
        processing_rules={},
        parquet_writer={},
        software_version="0.2.0.dev0",
        git_commit="7" * 40,
        git_dirty=False,
        python_version="3.12.0",
        uv_lock_sha256="8" * 64,
    )


def _edge(left: SequenceNode, right: SequenceNode) -> SimilarityEdge:
    return SimilarityEdge(
        left=left,
        right=right,
        query_accession=left.accession,
        target_accession=right.accession,
        fident=Decimal("0.30"),
        qcov=Decimal("0.80"),
        tcov=Decimal("0.80"),
        evalue=Decimal("0.001"),
        bits=Decimal("1"),
    )


def _pool_and_partition(
    class_shapes: Mapping[str, tuple[int, int]],
) -> tuple[CandidatePool, ComponentPartition]:
    records: list[CandidateRecord] = []
    edges: list[SimilarityEdge] = []
    next_index = 1
    for label, (candidate_count, component_count) in class_shapes.items():
        if component_count < 1 or component_count > candidate_count:
            raise ValueError("invalid synthetic class shape")
        class_records = [_record(label, next_index + offset) for offset in range(candidate_count)]
        next_index += candidate_count
        records.extend(class_records)
        groups: list[list[CandidateRecord]] = [[] for _ in range(component_count)]
        for offset, record in enumerate(class_records):
            groups[offset % component_count].append(record)
        for group in groups:
            anchor = SequenceNode(
                accession=group[0].accession,
                sequence_sha256=group[0].sequence_sha256,
            )
            for member in group[1:]:
                edges.append(
                    _edge(
                        anchor,
                        SequenceNode(
                            accession=member.accession,
                            sequence_sha256=member.sequence_sha256,
                        ),
                    )
                )
    nodes = tuple(
        SequenceNode(accession=record.accession, sequence_sha256=record.sequence_sha256)
        for record in records
    )
    partition = build_components(nodes, edges, Decimal("0.30"))
    pool = CandidatePool(
        records=tuple(records),
        build_manifest=_build_manifest(len(records)),
        dataset_sha256="9" * 64,
        build_manifest_sha256="a" * 64,
        fasta_sha256="b" * 64,
    )
    return pool, partition


def _rules() -> CohortSelectionConfig:
    return CohortSelectionConfig.model_validate(
        {
            "selection_rule_version": _RULE_VERSION,
            "label_field": "ec_level_2",
            "min_sequences_per_class": 40,
            "min_groups_per_class_at_cluster30": 10,
            "max_sequences_per_class": 250,
            "number_of_classes": 5,
            "seed": 42,
            "class_ranking": "capped_count_desc_group_count_desc_label_asc_v1",
            "member_ranking": "component_round_robin_sha256_v1",
        }
    )


def _feasibility() -> CohortFeasibilityConfig:
    return CohortFeasibilityConfig.model_validate(
        {
            "ratios": {"train": 0.70, "validation": 0.15, "test": 0.15},
            "ratio_tolerance": 0.05,
            "allocator": {
                "version": "greedy_component_loss_v1",
                "size_weight": 1.0,
                "class_balance_weight": 3.0,
                "group_count_weight": 0.5,
                "missing_class_weight": 10.0,
            },
        }
    )


def _write_discovery_artifacts(
    tmp_path: Path,
    pool: CandidatePool,
    partition: ComponentPartition,
    *,
    run_mode: str = "development",
) -> tuple[Path, Path]:
    from protein_split_audit.provenance import serialize_json_model
    from protein_split_audit.similarity.discovery import serialize_discovery_rows
    from protein_split_audit.similarity.schemas import (
        CandidateDiscoveryArtifactDigests,
        CandidateDiscoveryCommand,
        CandidateDiscoveryContentManifest,
        CandidateDiscoveryCounts,
        SimilarityArtifactDigest,
        SimilarityParentLineage,
    )

    tmp_path.mkdir(parents=True, exist_ok=True)
    labels = {record.accession: record.ec_level_2 for record in pool.records}
    serialized = serialize_discovery_rows(
        (), partition, ec_level_2_by_accession=labels, mmseqs_version="18-test"
    )
    components = tmp_path / "components.parquet"
    content_path = tmp_path / "components.json"
    components.write_bytes(serialized.component_manifest_bytes)
    component_ids = {row.component_id for row in partition.rows}
    per_class: dict[str, set[str]] = {}
    for row in partition.rows:
        per_class.setdefault(labels[row.node.accession], set()).add(row.component_id)
    counts = CandidateDiscoveryCounts(
        sequence_count=len(partition.rows),
        edge_count=0,
        component_count=len(component_ids),
        singleton_count=sum(row.component_size == 1 for row in partition.rows),
        largest_component_size=max(row.component_size for row in partition.rows),
        per_class_component_counts={label: len(ids) for label, ids in sorted(per_class.items())},
    )
    content = CandidateDiscoveryContentManifest(
        operation="candidate_discovery",
        name="candidate-pool-cluster30",
        run_mode=run_mode,
        configuration_file="configs/similarity/candidate-pool-cluster30.yaml",
        source_config_sha256="c" * 64,
        effective_config_sha256="d" * 64,
        parent_lineage=(
            SimilarityParentLineage(
                artifact_id=f"candidate-build:{pool.build_manifest_sha256}",
                manifest_sha256=pool.build_manifest_sha256,
                generation_git_commit=pool.build_manifest.git_commit,
                generation_git_dirty=pool.build_manifest.git_dirty,
            ),
        ),
        candidate_dataset_sha256=pool.dataset_sha256,
        build_manifest_sha256=pool.build_manifest_sha256,
        fasta_sha256=pool.fasta_sha256,
        command=CandidateDiscoveryCommand(
            sanitized_argv=("mmseqs", "easy-search", "<candidate-fasta>"),
            mmseqs_version="18-test",
            max_seqs=len(pool.records),
            fixed_parameters={"min_sequence_identity": "0.30"},
        ),
        counts=counts,
        artifacts=CandidateDiscoveryArtifactDigests(
            pair_table=SimilarityArtifactDigest(
                logical_path="data/processed/similarity/pairs.parquet",
                row_count=0,
                file_sha256=serialized.pair_table_sha256,
                semantic_sha256=serialized.pair_table_semantic_sha256,
            ),
            component_manifest=SimilarityArtifactDigest(
                logical_path="data/manifests/similarity/components.parquet",
                row_count=len(partition.rows),
                file_sha256=serialized.component_manifest_sha256,
                semantic_sha256=serialized.component_manifest_semantic_sha256,
            ),
        ),
        software_version="0.2.0.dev0",
        generation_git_commit="7" * 40,
        generation_git_dirty=run_mode == "development",
        python_version="3.12.0",
        uv_lock_sha256="8" * 64,
        release_eligible=run_mode == "freeze",
        ineligibility_reasons=(
            ("development_run_mode", "generation_git_dirty") if run_mode == "development" else ()
        ),
    )
    content_path.write_bytes(serialize_json_model(content))
    return components, content_path


def test_eligibility_uses_inclusive_count_and_component_boundaries() -> None:
    from protein_split_audit.cohort.select_cohort import profile_cohort_eligibility

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "1.2": (39, 10),
            "1.3": (40, 9),
            "1.4": (39, 9),
        }
    )

    profile = profile_cohort_eligibility(pool, partition, _rules())
    by_label = {row.ec_level_2: row for row in profile.classes}

    assert by_label["1.1"].eligible is True
    assert by_label["1.1"].exclusion_reasons == ()
    assert by_label["1.2"].exclusion_reasons == ("insufficient_candidates",)
    assert by_label["1.3"].exclusion_reasons == ("insufficient_cluster30_components",)
    assert by_label["1.4"].exclusion_reasons == (
        "insufficient_candidates",
        "insufficient_cluster30_components",
    )


def test_ranking_fails_clearly_with_four_eligible_classes_and_no_fallback() -> None:
    from protein_split_audit.cohort.select_cohort import (
        CohortSelectionError,
        profile_cohort_eligibility,
        rank_eligible_classes,
    )

    pool, partition = _pool_and_partition(
        {"1.1": (40, 10), "2.1": (40, 10), "3.1": (40, 10), "4.1": (40, 10)}
    )
    profile = profile_cohort_eligibility(pool, partition, _rules())

    with pytest.raises(
        CohortSelectionError,
        match=r"requires exactly 5 eligible.*found 4.*no fallback was applied",
    ):
        rank_eligible_classes(profile, _rules())


def test_ranking_uses_capped_count_components_and_numeric_ec_order() -> None:
    from protein_split_audit.cohort.select_cohort import (
        profile_cohort_eligibility,
        rank_eligible_classes,
    )

    shapes = {
        "1.10": (250, 12),
        "1.2": (250, 12),
        "2.1": (251, 11),
        "3.1": (249, 30),
        "4.1": (100, 20),
        "5.1": (90, 20),
    }
    pool, partition = _pool_and_partition(shapes)

    decisions = rank_eligible_classes(
        profile_cohort_eligibility(pool, partition, _rules()), _rules()
    )

    assert [decision.ec_level_2 for decision in decisions] == [
        "1.2",
        "1.10",
        "2.1",
        "3.1",
        "4.1",
        "5.1",
    ]
    assert [decision.selected for decision in decisions] == [True, True, True, True, True, False]
    assert [decision.eligible_rank for decision in decisions] == [1, 2, 3, 4, 5, 6]


def test_profile_rejects_wrong_threshold_and_identity_mismatch() -> None:
    from protein_split_audit.cohort.select_cohort import (
        CohortSelectionError,
        profile_cohort_eligibility,
    )

    pool, partition = _pool_and_partition({"1.1": (40, 10)})
    wrong_threshold = build_components(
        tuple(row.node for row in partition.rows), (), Decimal("0.50")
    )
    with pytest.raises(CohortSelectionError, match=r"exactly 0\.30"):
        profile_cohort_eligibility(pool, wrong_threshold, _rules())

    first = partition.rows[0]
    changed_node = replace(first.node, sequence_sha256="f" * 64)
    changed_rows = (replace(first, node=changed_node), *partition.rows[1:])
    object.__setattr__(partition, "rows", tuple(changed_rows))
    with pytest.raises(CohortSelectionError, match="candidate pool and discovery partition"):
        profile_cohort_eligibility(pool, partition, _rules())


def test_member_cap_is_component_aware_and_shuffle_stable() -> None:
    from protein_split_audit.cohort.select_cohort import (
        profile_cohort_eligibility,
        rank_eligible_classes,
        select_cohort_members,
    )

    pool, partition = _pool_and_partition(
        {
            "1.1": (251, 20),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )
    rules = _rules()
    decisions = rank_eligible_classes(profile_cohort_eligibility(pool, partition, rules), rules)
    baseline = select_cohort_members(pool, partition, decisions, rules)

    selected_11 = tuple(member for member in baseline if member.candidate.ec_level_2 == "1.1")
    assert len(selected_11) == 250
    assert len({member.discovery_component_id_cluster30 for member in selected_11}) == 20
    assert len(baseline) == 410
    assert baseline == tuple(
        sorted(
            baseline,
            key=lambda member: (
                tuple(int(part) for part in member.candidate.ec_level_2.split(".")),
                member.candidate.ec_level_2,
                member.candidate.accession,
                member.candidate.sequence_sha256,
            ),
        )
    )

    generator = random.Random(42)
    shuffled_records = list(pool.records)
    shuffled_rows = list(partition.rows)
    generator.shuffle(shuffled_records)
    generator.shuffle(shuffled_rows)
    shuffled_pool = pool.model_copy(update={"records": tuple(shuffled_records)})
    shuffled_partition = ComponentPartition(
        threshold=partition.threshold,
        rows=tuple(shuffled_rows),
    )
    replay_decisions = rank_eligible_classes(
        profile_cohort_eligibility(shuffled_pool, shuffled_partition, rules), rules
    )

    assert (
        select_cohort_members(shuffled_pool, shuffled_partition, replay_decisions, rules)
        == baseline
    )


def test_profile_rejects_malformed_ec_level_2() -> None:
    from protein_split_audit.cohort.select_cohort import (
        CohortSelectionError,
        profile_cohort_eligibility,
    )

    pool, partition = _pool_and_partition({"1.1": (40, 10)})
    malformed = pool.records[0].model_copy(update={"ec_level_2": "1.x"})
    invalid_pool = pool.model_copy(update={"records": (malformed, *pool.records[1:])})

    with pytest.raises(CohortSelectionError, match="EC-level-2"):
        profile_cohort_eligibility(invalid_pool, partition, _rules())


def test_select_cohort_composes_exact_feasibility_and_recomputes() -> None:
    from protein_split_audit.cohort.select_cohort import select_cohort, validate_cohort_selection

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )

    selected = select_cohort(pool, partition, _rules(), _feasibility())

    assert selected.selected_labels == ("1.1", "2.1", "3.1", "4.1", "5.1")
    assert len(selected.members) == 200
    assert selected.feasibility.feasible is True
    assert selected.source_hashes.dataset_sha256 == pool.dataset_sha256
    validate_cohort_selection(selected, pool, partition, _rules(), _feasibility())


def test_validate_cohort_selection_rejects_mutated_recomputation() -> None:
    from protein_split_audit.cohort.select_cohort import (
        CohortSelectionError,
        select_cohort,
        validate_cohort_selection,
    )

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )
    selected = select_cohort(pool, partition, _rules(), _feasibility())
    mutated = replace(selected, members=tuple(reversed(selected.members)))

    with pytest.raises(CohortSelectionError, match="recomputation"):
        validate_cohort_selection(mutated, pool, partition, _rules(), _feasibility())


def test_load_discovery_partition_reconciles_schema_hashes_and_candidate_identity(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.artifacts import load_discovery_partition

    pool, partition = _pool_and_partition({"1.1": (40, 10)})
    components, content = _write_discovery_artifacts(tmp_path, pool, partition)

    loaded = load_discovery_partition(components, content, pool=pool)

    assert loaded.partition == partition
    assert loaded.content_manifest.counts.sequence_count == 40
    assert loaded.content_manifest_sha256 == sha256_bytes(content.read_bytes())


def test_load_discovery_partition_rejects_stale_file_or_parent_hash(tmp_path: Path) -> None:
    from protein_split_audit.cohort.artifacts import CohortArtifactError, load_discovery_partition

    pool, partition = _pool_and_partition({"1.1": (40, 10)})
    components, content = _write_discovery_artifacts(tmp_path, pool, partition)
    components.write_bytes(components.read_bytes() + b"tampered")
    with pytest.raises(CohortArtifactError, match="component manifest hash"):
        load_discovery_partition(components, content, pool=pool)

    components, content = _write_discovery_artifacts(tmp_path / "parent", pool, partition)
    stale_pool = pool.model_copy(update={"build_manifest_sha256": "0" * 64})
    with pytest.raises(CohortArtifactError, match="candidate input hashes"):
        load_discovery_partition(components, content, pool=stale_pool)


def test_serialize_selected_cohort_is_deterministic_parquet_and_fasta() -> None:
    from protein_split_audit.cohort.artifacts import (
        COHORT_MANIFEST_SCHEMA,
        serialize_selected_cohort,
    )
    from protein_split_audit.cohort.select_cohort import select_cohort

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )
    selected = select_cohort(pool, partition, _rules(), _feasibility())

    first = serialize_selected_cohort(
        selected,
        cohort_version="pilot-v1-candidate",
        selection_rule_version=_RULE_VERSION,
        source_dataset_manifest="data/manifests/pilot.build.json",
    )
    second = serialize_selected_cohort(
        selected,
        cohort_version="pilot-v1-candidate",
        selection_rule_version=_RULE_VERSION,
        source_dataset_manifest="data/manifests/pilot.build.json",
    )

    assert first == second
    table = pq.read_table(pa.BufferReader(first.parquet_bytes))
    assert table.schema.equals(COHORT_MANIFEST_SCHEMA, check_metadata=False)
    assert table.num_rows == 200
    assert table.column_names == COHORT_MANIFEST_SCHEMA.names
    rows = table.to_pylist()
    assert rows[0]["ec_level_2"] == "1.1"
    assert rows[0]["source_dataset_manifest"] == "data/manifests/pilot.build.json"
    assert len(rows[0]["sequence_sha256"]) == 32
    assert first.fasta_bytes.startswith(b">sp|")
    assert b"pilot-v1-candidate" not in first.fasta_bytes
    assert first.parquet_sha256 == sha256_bytes(first.parquet_bytes)
    assert first.fasta_sha256 == sha256_bytes(first.fasta_bytes)


def test_development_content_manifest_is_aggregate_deterministic_and_ineligible(
    tmp_path: Path,
) -> None:
    from protein_split_audit.cohort.artifacts import (
        CohortParentLineage,
        build_development_content_manifest,
        load_discovery_partition,
        serialize_selected_cohort,
    )
    from protein_split_audit.cohort.select_cohort import select_cohort
    from protein_split_audit.config import load_cohort_config_document
    from protein_split_audit.provenance import serialize_json_model

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )
    component_path, content_path = _write_discovery_artifacts(tmp_path / "content", pool, partition)
    discovery = load_discovery_partition(component_path, content_path, pool=pool)
    selected = select_cohort(pool, discovery.partition, _rules(), _feasibility())
    document = load_cohort_config_document(_PROJECT_ROOT / "configs/cohort/pilot.yaml")
    serialized = serialize_selected_cohort(
        selected,
        cohort_version="pilot-v1-candidate",
        selection_rule_version=_RULE_VERSION,
        source_dataset_manifest="data/manifests/pilot.build.json",
    )
    parents = (
        CohortParentLineage(
            artifact_kind="download",
            manifest_sha256="1" * 64,
            generation_git_commit="7" * 40,
            generation_git_dirty=True,
        ),
        CohortParentLineage(
            artifact_kind="build",
            manifest_sha256=pool.build_manifest_sha256,
            generation_git_commit=pool.build_manifest.git_commit,
            generation_git_dirty=pool.build_manifest.git_dirty,
        ),
        CohortParentLineage(
            artifact_kind="discovery30",
            manifest_sha256=discovery.content_manifest_sha256,
            generation_git_commit=discovery.content_manifest.generation_git_commit,
            generation_git_dirty=discovery.content_manifest.generation_git_dirty,
        ),
    )

    manifest = build_development_content_manifest(
        document,
        selected=selected,
        discovery=discovery,
        serialized=serialized,
        parent_lineage=parents,
        generation_git=GitMetadata(available=True, commit="7" * 40, dirty=True),
        uv_lock_sha256="8" * 64,
        project_root=_PROJECT_ROOT,
    )
    content = serialize_json_model(manifest)

    assert manifest.cohort_version == "pilot-v1-candidate"
    assert manifest.release_eligible is False
    assert "development_run_mode" in manifest.ineligibility_reasons
    assert manifest.model_performance_used is False
    assert manifest.selection_evidence == (
        "candidate_count",
        "discovery_component_count",
    )
    assert manifest.artifacts.cohort_manifest.file_sha256 == serialized.parquet_sha256
    assert manifest.artifacts.fasta.file_sha256 == serialized.fasta_sha256
    assert b"P000" not in content
    assert b"sequence_sha256" not in content
    assert b"timestamp" not in content
    assert b"built_at" not in content


def test_build_cohort_publishes_provisional_bundle_and_refuses_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cohort.artifacts as artifact_module
    from protein_split_audit.cohort.artifacts import (
        CohortArtifactError,
        build_cohort,
        validate_cohort_artifacts,
    )
    from protein_split_audit.config import load_cohort_config_document
    from protein_split_audit.provenance import DownloadManifest

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )
    component_path, discovery_content = _write_discovery_artifacts(
        tmp_path / "inputs", pool, partition
    )
    mapping = yaml.safe_load(
        (_PROJECT_ROOT / "configs/cohort/pilot.yaml").read_text(encoding="utf-8")
    )
    mapping["input"] = {
        "candidate_dataset": "inputs/pilot.parquet",
        "candidate_fasta": "inputs/pilot.fasta",
        "raw_download": "inputs/pilot.tsv.gz",
        "build_manifest": "inputs/pilot.build.json",
        "download_manifest": "inputs/pilot.download.json",
        "discovery_components": component_path.relative_to(tmp_path).as_posix(),
        "discovery_content_manifest": discovery_content.relative_to(tmp_path).as_posix(),
    }
    mapping["output"] = {
        "cohort_manifest": "outputs/pilot-v1-candidate.parquet",
        "content_manifest": "outputs/pilot-v1-candidate.json",
        "fasta": "outputs/pilot-v1-candidate.fasta",
        "run_dir": "runs/cohort-pilot-v1-candidate",
        "overwrite": False,
    }
    config_path = tmp_path / "cohort.yaml"
    config_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    (tmp_path / "uv.lock").write_bytes(b"locked\n")
    document = load_cohort_config_document(config_path)
    download = DownloadManifest.model_construct(
        git_commit="7" * 40,
        git_dirty=True,
    )
    lineage = SimpleNamespace(
        download_manifest=download,
        build_manifest=pool.build_manifest,
        pool=pool,
        download_manifest_sha256="1" * 64,
        build_manifest_sha256=pool.build_manifest_sha256,
    )
    monkeypatch.setattr(
        artifact_module, "load_candidate_lineage", lambda *_args, **_kwargs: lineage
    )
    monkeypatch.setattr(
        artifact_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=True),
    )

    result = build_cohort(
        document,
        project_root=tmp_path,
        now=lambda: datetime(2026, 7, 15, 1, 2, 3, tzinfo=UTC),
    )

    assert result.cohort_manifest.is_file()
    assert result.fasta.is_file()
    assert result.content_manifest.is_file()
    assert result.run_provenance.is_file()
    assert result.selected_count == 200
    content = result.content_manifest.read_bytes()
    provenance = result.run_provenance.read_bytes()
    assert b"pilot-v1-candidate" in content
    assert b'release_eligible":false' not in content  # pretty JSON retains a space
    assert b'"release_eligible": false' in content
    assert b"2026-07-15T01:02:03Z" not in content
    assert b"2026-07-15T01:02:03Z" in provenance
    validation = validate_cohort_artifacts(
        result.cohort_manifest,
        result.content_manifest,
        project_root=tmp_path,
    )
    assert validation.selected_count == 200
    assert validation.selected_labels == ("1.1", "2.1", "3.1", "4.1", "5.1")
    with pytest.raises(CohortArtifactError, match="publication"):
        build_cohort(document, project_root=tmp_path)


def test_build_cohort_freeze_validates_review_and_publishes_release_eligible_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cohort.artifacts as artifact_module
    from protein_split_audit.cohort.artifacts import build_cohort, validate_cohort_artifacts
    from protein_split_audit.cohort.freeze import FreezeReview
    from protein_split_audit.cohort.regeneration import RegenerationDifference
    from protein_split_audit.config import load_cohort_config_document
    from protein_split_audit.provenance import DownloadManifest, serialize_json_model

    pool, partition = _pool_and_partition(
        {
            "1.1": (40, 10),
            "2.1": (40, 10),
            "3.1": (40, 10),
            "4.1": (40, 10),
            "5.1": (40, 10),
        }
    )
    component_path, discovery_content = _write_discovery_artifacts(
        tmp_path / "inputs",
        pool,
        partition,
        run_mode="freeze",
    )

    mapping = yaml.safe_load(
        (_PROJECT_ROOT / "configs/cohort/pilot.yaml").read_text(encoding="utf-8")
    )
    mapping["run_mode"] = "freeze"
    mapping["cohort_version"] = "pilot-v1"
    mapping["input"] = {
        "candidate_dataset": "inputs/pilot.parquet",
        "candidate_fasta": "inputs/pilot.fasta",
        "raw_download": "inputs/pilot.tsv.gz",
        "build_manifest": "inputs/pilot.build.json",
        "download_manifest": "inputs/pilot.download.json",
        "discovery_components": component_path.relative_to(tmp_path).as_posix(),
        "discovery_content_manifest": discovery_content.relative_to(tmp_path).as_posix(),
        "difference_report": "inputs/difference.json",
        "review_attestation": "inputs/review.json",
    }
    mapping["output"] = {
        "cohort_manifest": "outputs/pilot-v1.parquet",
        "content_manifest": "outputs/pilot-v1.json",
        "fasta": "outputs/pilot-v1.fasta",
        "run_dir": "runs/cohort-pilot-v1",
        "overwrite": False,
    }
    config_path = tmp_path / "freeze.yaml"
    config_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    (tmp_path / "uv.lock").write_bytes(b"locked\n")
    document = load_cohort_config_document(config_path)

    download = DownloadManifest.model_construct(
        git_commit="7" * 40,
        git_dirty=False,
        uv_lock_sha256="8" * 64,
    )
    lineage = SimpleNamespace(
        download_manifest=download,
        build_manifest=pool.build_manifest,
        pool=pool,
        download_manifest_sha256="1" * 64,
        build_manifest_sha256=pool.build_manifest_sha256,
        uv_lock_sha256="8" * 64,
    )
    difference = RegenerationDifference(
        report={
            "historical_identity": {
                "download_manifest_sha256": "2" * 64,
                "build_manifest_sha256": "3" * 64,
            },
            "regenerated_identity": {
                "download_manifest_sha256": "1" * 64,
                "build_manifest_sha256": pool.build_manifest_sha256,
            },
        },
        aggregate_bytes=b"reviewed-difference\n",
        aggregate_sha256="4" * 64,
        detail_parquet_bytes=b"",
        detail_file_sha256="5" * 64,
        detail_semantic_sha256="6" * 64,
    )
    discovery_hash = sha256_bytes(discovery_content.read_bytes())
    review = FreezeReview(
        decision="approved-for-pilot-v1-freeze",
        selection_rule_version=_RULE_VERSION,
        generation_git_commit="7" * 40,
        uv_lock_sha256="8" * 64,
        historical_download_manifest_sha256="2" * 64,
        historical_build_manifest_sha256="3" * 64,
        regenerated_download_manifest_sha256="1" * 64,
        regenerated_build_manifest_sha256=pool.build_manifest_sha256,
        difference_report_sha256=difference.aggregate_sha256,
        discovery_content_manifest_sha256=discovery_hash,
        approval_reference="maintainer-review:test",
    )
    (tmp_path / "inputs/difference.json").write_bytes(difference.aggregate_bytes)
    (tmp_path / "inputs/review.json").write_bytes(serialize_json_model(review))
    monkeypatch.setattr(
        artifact_module, "load_candidate_lineage", lambda *_args, **_kwargs: lineage
    )
    monkeypatch.setattr(
        artifact_module,
        "load_regeneration_difference_report",
        lambda _path: difference,
    )
    monkeypatch.setattr(
        artifact_module,
        "git_metadata",
        lambda _root: GitMetadata(available=True, commit="7" * 40, dirty=False),
    )
    actual_sha256_file = artifact_module.sha256_file
    monkeypatch.setattr(
        artifact_module,
        "sha256_file",
        lambda path: "8" * 64 if path.name == "uv.lock" else actual_sha256_file(path),
    )

    result = build_cohort(document, project_root=tmp_path)

    assert result.selected_count == 200
    assert result.content.cohort_version == "pilot-v1"
    assert result.content.provisional is False
    assert result.content.release_eligible is True
    assert result.content.ineligibility_reasons == ()
    assert {parent.artifact_kind for parent in result.content.parent_lineage} == {
        "download",
        "build",
        "discovery30",
        "difference",
        "review",
    }
    assert result.cohort_manifest.is_file()
    assert result.fasta.is_file()
    assert result.content_manifest.is_file()
    validation = validate_cohort_artifacts(
        result.cohort_manifest,
        result.content_manifest,
        project_root=tmp_path,
    )
    assert validation.selected_count == 200
