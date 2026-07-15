# SPDX-License-Identifier: Apache-2.0

"""Command-line interface for project-foundation diagnostics."""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer

from protein_split_audit import __version__
from protein_split_audit.cohort.artifacts import (
    CohortArtifactError,
    build_cohort,
    validate_cohort_artifacts,
)
from protein_split_audit.cohort.profile_cohort import (
    CandidateProfileError,
    load_candidate_pool,
    profile_candidate_pool,
    write_candidate_profile,
)
from protein_split_audit.config import (
    load_build_config,
    load_cohort_config_document,
    load_download_config,
    load_experiment_config,
    load_similarity_config,
    load_similarity_config_document,
)
from protein_split_audit.data.build_candidates import BuildError, build_candidate_dataset
from protein_split_audit.data.download_uniprot import DownloadError, download_uniprot
from protein_split_audit.data.profile import ProfileError, profile_candidate_dataset
from protein_split_audit.evaluation.standalone import verify_evaluation_run
from protein_split_audit.experiments.aggregate import write_validation_aggregates
from protein_split_audit.experiments.matrix import run_matrix
from protein_split_audit.experiments.replay import compare_validation_replays
from protein_split_audit.experiments.runner import run_experiment_cell
from protein_split_audit.experiments.test_gate import RealTestAccessDenied, enforce_test_gate
from protein_split_audit.features.extract import extract_feature_cache
from protein_split_audit.models.standalone import train_cached_model
from protein_split_audit.paths import find_project_root, is_writable_directory
from protein_split_audit.provenance import git_metadata
from protein_split_audit.similarity.audit_train_test import (
    SimilarityAuditError,
    audit_train_test,
)
from protein_split_audit.similarity.discovery import (
    DiscoveryError,
    create_discovery_run_context,
    discover_candidate_pool,
)
from protein_split_audit.similarity.formal import (
    FormalSimilarityError,
    build_base_similarity,
    derive_similarity,
)
from protein_split_audit.similarity.mmseqs import MmseqsProbeError, probe_mmseqs
from protein_split_audit.splits.artifacts import SplitArtifactError, run_split

app = typer.Typer(
    add_completion=False,
    help="Foundation diagnostics for ProteinSplitAudit.",
    invoke_without_command=True,
    no_args_is_help=True,
)
data_app = typer.Typer(help="Source-data commands.", no_args_is_help=True)
cohort_app = typer.Typer(help="Pilot-cohort commands.", no_args_is_help=True)
similarity_app = typer.Typer(help="Sequence-similarity commands.", no_args_is_help=True)
split_app = typer.Typer(help="Dataset-split commands.", no_args_is_help=True)
feature_app = typer.Typer(help="Classical feature commands.", no_args_is_help=True)
model_app = typer.Typer(help="Classical baseline commands.", no_args_is_help=True)
evaluate_app = typer.Typer(help="Validation evaluation commands.", no_args_is_help=True)
experiment_app = typer.Typer(help="Validation experiment commands.", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(cohort_app, name="cohort")
app.add_typer(similarity_app, name="similarity")
app.add_typer(split_app, name="split")
app.add_typer(feature_app, name="feature")
app.add_typer(model_app, name="model")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(experiment_app, name="experiment")


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One diagnostic result."""

    name: str
    status: Literal["PASS", "WARN", "FAIL", "INFO"]
    detail: str
    required: bool = True


def _directory_checks(root: Path) -> list[DoctorCheck]:
    return [
        DoctorCheck(
            name=f"Writable {name} directory",
            status="PASS" if is_writable_directory(root / name) else "FAIL",
            detail=str(root / name),
        )
        for name in ("data", "cache", "results")
    ]


def _cache_root_is_writable(path: Path) -> bool:
    """Return whether a cache directory exists or can be created below a writable parent."""

    resolved = path.expanduser().resolve()
    if resolved.exists():
        return resolved.is_dir() and os.access(resolved, os.W_OK | os.X_OK)

    ancestor = resolved.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    return ancestor.is_dir() and os.access(ancestor, os.W_OK | os.X_OK)


def _mmseqs_checks(executable: str) -> list[DoctorCheck]:
    """Report MMseqs2 discovery without making it a foundation requirement."""

    try:
        tool = probe_mmseqs(executable)
    except MmseqsProbeError as error:
        executable_check = DoctorCheck(
            "MMseqs2 executable",
            "PASS" if error.executable is not None else "WARN",
            str(error.executable) if error.executable is not None else str(error),
            required=False,
        )
        return [
            executable_check,
            DoctorCheck("MMseqs2 version", "WARN", str(error), required=False),
        ]

    return [
        DoctorCheck("MMseqs2 executable", "PASS", str(tool.executable), required=False),
        DoctorCheck("MMseqs2 version", "PASS", tool.version, required=False),
    ]


def run_doctor(
    start: Path | None = None,
    *,
    similarity_config: Path | None = None,
) -> list[DoctorCheck]:
    """Run local, non-networked project-foundation diagnostics."""

    python_supported = (3, 12) <= sys.version_info[:2] < (3, 13)
    checks = [
        DoctorCheck(
            "ProteinSplitAudit version",
            "PASS" if __version__ != "0.0.0+unknown" else "FAIL",
            __version__,
        ),
        DoctorCheck(
            "Python version",
            "PASS" if python_supported else "FAIL",
            platform.python_version(),
        ),
        DoctorCheck("Operating system", "INFO", platform.system(), required=False),
        DoctorCheck("Architecture", "INFO", platform.machine(), required=False),
        DoctorCheck(
            "Logical CPUs",
            "INFO",
            str(os.cpu_count()) if os.cpu_count() is not None else "unknown",
            required=False,
        ),
    ]

    root = find_project_root(start)
    if root is None:
        checks.append(DoctorCheck("Project root", "FAIL", "not found"))
        return checks

    checks.append(DoctorCheck("Project root", "PASS", str(root)))
    checks.extend(_directory_checks(root))
    checks.append(
        DoctorCheck(
            "uv.lock",
            "PASS" if (root / "uv.lock").is_file() else "FAIL",
            str(root / "uv.lock"),
        )
    )

    git = git_metadata(root)
    if not git.available:
        checks.append(DoctorCheck("Git working tree", "WARN", "Git metadata unavailable"))
    elif git.dirty:
        checks.append(DoctorCheck("Git working tree", "WARN", "working tree is dirty"))
    elif git.dirty is False:
        checks.append(DoctorCheck("Git working tree", "PASS", "working tree is clean"))
    else:
        checks.append(DoctorCheck("Git working tree", "WARN", "cleanliness unavailable"))

    executable = "mmseqs"
    cache_root = root / "cache/mmseqs"
    if similarity_config is not None:
        config = load_similarity_config(similarity_config)
        executable = config.runtime.executable
        cache_root = config.runtime.cache_root

    checks.extend(
        [
            DoctorCheck(
                "MMseqs2 cache writable",
                "PASS" if _cache_root_is_writable(cache_root) else "FAIL",
                str(cache_root.expanduser().resolve()),
            ),
            DoctorCheck(
                "PyTorch (future, optional)",
                "INFO",
                "available" if importlib.util.find_spec("torch") else "not installed",
                required=False,
            ),
        ]
    )
    checks.extend(_mmseqs_checks(executable))
    return checks


@app.callback()
def root_callback(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the installed version and exit.", is_eager=True),
    ] = False,
) -> None:
    """Run ProteinSplitAudit project-foundation commands."""

    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def doctor(
    similarity_config: Annotated[
        Path | None,
        typer.Option(
            "--similarity-config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Similarity YAML whose runtime executable and cache root should be checked.",
        ),
    ] = None,
) -> None:
    """Check the local project foundation without network access."""

    try:
        checks = run_doctor(similarity_config=similarity_config)
    except (OSError, ValueError) as error:
        typer.echo(f"Error: invalid similarity configuration: {error}", err=True)
        raise typer.Exit(code=2) from error
    for check in checks:
        typer.echo(f"[{check.status}] {check.name}: {check.detail}")

    failed = any(check.required and check.status == "FAIL" for check in checks)
    typer.echo(f"Overall: {'FAIL' if failed else 'PASS'}")
    if failed:
        raise typer.Exit(code=1)


def _not_implemented(command: str) -> None:
    """Fail a registered future command without reading inputs or producing outputs."""

    typer.echo(f"Error: {command} is not implemented in this task.", err=True)
    raise typer.Exit(code=1)


@cohort_app.command("profile")
def cohort_profile(
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Processed candidate Parquet dataset.",
        ),
    ],
    build_manifest: Annotated[
        Path,
        typer.Option(
            "--build-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Build manifest matching the candidate dataset.",
        ),
    ],
    fasta: Annotated[
        Path,
        typer.Option(
            "--fasta",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Candidate FASTA matching the candidate dataset.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            file_okay=False,
            resolve_path=True,
            help="Destination for aggregate cohort profile outputs.",
        ),
    ],
) -> None:
    """Validate and profile the candidate pool without selecting a cohort."""

    try:
        pool = load_candidate_pool(dataset, build_manifest, fasta)
        profile = profile_candidate_pool(pool)
        paths = write_candidate_profile(profile, output_dir)
    except (CandidateProfileError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(
        f"Profiled {profile.candidate_count} candidates across "
        f"{len(profile.ec_level_2_class_counts)} EC-level-2 classes"
    )
    typer.echo(f"Wrote {len(paths)} aggregate artifacts")


@cohort_app.command("select")
def cohort_select(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Validated cohort selection YAML configuration.",
        ),
    ],
) -> None:
    """Build a deterministic provisional cohort or enforce the freeze gate."""

    project_root = find_project_root(config)
    if project_root is None:
        typer.echo("Error: project root not found from cohort configuration", err=True)
        raise typer.Exit(code=1)
    try:
        document = load_cohort_config_document(config)
        result = build_cohort(document, project_root=project_root)
    except (CohortArtifactError, OSError, RuntimeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    status = "Frozen pilot-v1" if result.content.release_eligible else "Provisional cohort"
    typer.echo(f"{status} selected {result.selected_count} candidates")
    typer.echo(f"Selected EC-level-2 classes: {', '.join(result.selected_labels)}")
    typer.echo(f"Release eligible: {'yes' if result.content.release_eligible else 'no'}")
    typer.echo(f"Manifest: {result.cohort_manifest}")
    typer.echo(f"FASTA: {result.fasta}")
    typer.echo(f"Content manifest: {result.content_manifest}")


@cohort_app.command("validate")
def cohort_validate(
    manifest: Annotated[
        Path,
        typer.Option(
            "--manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Pilot cohort Parquet manifest.",
        ),
    ],
    content_manifest: Annotated[
        Path,
        typer.Option(
            "--content-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Pilot cohort content manifest.",
        ),
    ],
) -> None:
    """Recompute and validate a provisional cohort artifact bundle."""

    project_root = find_project_root(content_manifest)
    if project_root is None:
        typer.echo("Error: project root not found from cohort manifest", err=True)
        raise typer.Exit(code=1)
    try:
        report = validate_cohort_artifacts(
            manifest,
            content_manifest,
            project_root=project_root,
        )
    except (OSError, RuntimeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    cohort_label = "provisional cohort" if report.provisional else f"frozen {report.cohort_version}"
    typer.echo(f"Validated {cohort_label}: {report.selected_count} candidates")
    typer.echo(f"Selected EC-level-2 classes: {', '.join(report.selected_labels)}")


@similarity_app.command("cluster")
def similarity_cluster(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Validated similarity clustering YAML configuration.",
        ),
    ],
) -> None:
    """Run candidate discovery or formal frozen-cohort grouping."""

    try:
        document = load_similarity_config_document(config)
    except (OSError, ValueError) as error:
        typer.echo(f"Error: invalid similarity configuration: {error}", err=True)
        raise typer.Exit(code=2) from error

    try:
        if document.config.operation == "candidate_discovery":
            artifacts = discover_candidate_pool(
                document,
                run_context_factory=create_discovery_run_context,
            )
            typer.echo(
                f"Discovered {artifacts.sequence_count} sequences with "
                f"{artifacts.edge_count} normalized pair edge(s) in "
                f"{artifacts.component_count} component(s) "
                f"({artifacts.singleton_count} singletons; largest "
                f"{artifacts.largest_component_size})"
            )
            typer.echo("Published pair table, component manifest, and content manifest")
            typer.echo("Published local run provenance")
            return
        project_root = find_project_root(config)
        if project_root is None:
            typer.echo("Error: project root not found from similarity configuration", err=True)
            raise typer.Exit(code=1)
        if document.config.operation == "cohort_cluster_base":
            formal = build_base_similarity(document, project_root=project_root)
        elif document.config.operation == "cohort_cluster_derived":
            formal = derive_similarity(document, project_root=project_root)
        else:
            typer.echo("Error: audit configs must use similarity audit", err=True)
            raise typer.Exit(code=2)
    except (DiscoveryError, FormalSimilarityError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except (OSError, ValueError) as error:
        typer.echo("Error: candidate discovery failed during local execution.", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(
        f"Generated {document.config.name}: {len(formal.partition.rows)} sequences, "
        f"{len(set(formal.partition.node_to_component.values()))} strict components"
    )
    typer.echo(f"Cluster manifest: {formal.cluster_manifest_path}")
    typer.echo(f"Content manifest: {formal.content_manifest_path}")


@similarity_app.command("validate")
def similarity_validate(
    manifest: Annotated[
        Path,
        typer.Option("--manifest", help="Similarity cluster Parquet manifest."),
    ],
    content_manifest: Annotated[
        Path,
        typer.Option("--content-manifest", help="Similarity content manifest."),
    ],
) -> None:
    """Validate similarity artifacts in a later task."""

    _not_implemented("similarity validate")


@similarity_app.command("audit")
def similarity_audit(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Validated train-test audit YAML configuration.",
        ),
    ],
) -> None:
    """Run an independent test-to-train similarity audit."""

    project_root = find_project_root(config)
    if project_root is None:
        typer.echo("Error: project root not found from audit configuration", err=True)
        raise typer.Exit(code=1)
    try:
        document = load_similarity_config_document(config)
        artifacts = audit_train_test(document, project_root=project_root)
    except (OSError, ValueError, SimilarityAuditError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Audit manifest: {artifacts.audit_manifest_path}")
    typer.echo(f"Summary: {artifacts.summary_path}")
    typer.echo(f"Release eligible: {'yes' if artifacts.release_eligible else 'no'}")


@split_app.command("create")
def split_create(
    config: Annotated[
        Path,
        typer.Option("--config", help="Validated dataset split YAML configuration."),
    ],
) -> None:
    """Create a deterministic random or whole-component split."""

    project_root = find_project_root(config)
    if project_root is None:
        typer.echo("Error: project root not found from split configuration", err=True)
        raise typer.Exit(code=1)
    try:
        artifacts = run_split(config, project_root=project_root)
    except (OSError, ValueError, SplitArtifactError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Created {artifacts.assignment.name} split")
    typer.echo(f"Manifest: {artifacts.manifest_path}")
    typer.echo(f"Content manifest: {artifacts.content_manifest_path}")
    typer.echo(f"Release eligible: {'yes' if artifacts.release_eligible else 'no'}")


@split_app.command("validate")
def split_validate(
    manifest: Annotated[
        Path,
        typer.Option("--manifest", help="Dataset split Parquet manifest."),
    ],
    config: Annotated[
        Path,
        typer.Option("--config", help="Validated dataset split YAML configuration."),
    ],
) -> None:
    """Validate a configured split in a later task."""

    _not_implemented("split validate")


@data_app.command("download")
def data_download(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Validated UniProt pilot dataset YAML configuration.",
        ),
    ],
) -> None:
    """Download paginated UniProtKB TSV data with provenance."""

    project_root = find_project_root(config)
    if project_root is None:
        typer.echo("Error: project root not found from configuration path", err=True)
        raise typer.Exit(code=1)

    try:
        download_config = load_download_config(config)
        result = download_uniprot(download_config, project_root=project_root)
    except (DownloadError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"Downloaded {result.manifest.record_count} records")
    typer.echo(f"Raw data: {result.compressed_path}")
    typer.echo(f"Manifest: {result.manifest_path}")


@data_app.command("build")
def data_build(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Validated candidate-dataset YAML configuration.",
        ),
    ],
) -> None:
    """Build exact-deduplicated candidate Parquet and FASTA artifacts."""

    project_root = find_project_root(config)
    if project_root is None:
        typer.echo("Error: project root not found from configuration path", err=True)
        raise typer.Exit(code=1)

    try:
        build_config = load_build_config(config)
        result = build_candidate_dataset(
            build_config,
            config_path=config,
            project_root=project_root,
        )
    except (BuildError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"Retained {result.manifest.counts.retained_candidates} candidates")
    typer.echo(f"Parquet: {result.parquet_path}")
    typer.echo(f"FASTA: {result.fasta_path}")
    typer.echo(f"Manifest: {result.manifest_path}")


@data_app.command("profile")
def data_profile(
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Processed candidate Parquet dataset.",
        ),
    ],
    build_manifest: Annotated[
        Path,
        typer.Option(
            "--build-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Build provenance manifest matching the dataset.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            file_okay=False,
            resolve_path=True,
            help="Directory for deterministic aggregate profile summaries.",
        ),
    ],
) -> None:
    """Write aggregate-only candidate dataset profile summaries."""

    try:
        result = profile_candidate_dataset(
            dataset_path=dataset,
            build_manifest_path=build_manifest,
            output_dir=output_dir,
        )
    except (ProfileError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"Profile summary: {result.profile_summary_path}")
    typer.echo(f"Profile artifacts: {len(result.artifact_paths)}")


@feature_app.command("extract")
def feature_extract(
    config: Annotated[
        Path,
        typer.Option("--config", exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    cohort_manifest: Annotated[
        Path,
        typer.Option(
            "--cohort-manifest", exists=True, dir_okay=False, readable=True, resolve_path=True
        ),
    ],
    cohort_content_manifest: Annotated[
        Path,
        typer.Option(
            "--cohort-content-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    cohort_fasta: Annotated[
        Path,
        typer.Option(
            "--cohort-fasta", exists=True, dir_okay=False, readable=True, resolve_path=True
        ),
    ],
    split_manifest: Annotated[
        Path,
        typer.Option(
            "--split-manifest", exists=True, dir_okay=False, readable=True, resolve_path=True
        ),
    ],
    split_content_manifest: Annotated[
        Path,
        typer.Option(
            "--split-content-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    evaluation_split: Annotated[
        Literal["validation"],
        typer.Option("--evaluation-split", help="Only Validation is authorized in v0.3."),
    ] = "validation",
) -> None:
    """Extract immutable Train/Validation features without reading row labels."""

    del evaluation_split
    project_root = find_project_root(config)
    if project_root is None:
        typer.echo("Error: project root not found from feature configuration", err=True)
        raise typer.Exit(code=1)
    try:
        result = extract_feature_cache(
            config_path=config,
            cohort_manifest=cohort_manifest,
            cohort_content_manifest=cohort_content_manifest,
            cohort_fasta=cohort_fasta,
            split_manifest=split_manifest,
            split_content_manifest=split_content_manifest,
            cache_root=project_root / "cache/features",
        )
    except (FileExistsError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Feature cache: {result.directory}")
    typer.echo(f"Cache key: {result.cache_key}")


@model_app.command("train")
def model_train(
    feature_manifest: Annotated[
        Path,
        typer.Option(
            "--feature-manifest", exists=True, dir_okay=False, readable=True, resolve_path=True
        ),
    ],
    split_manifest: Annotated[
        Path,
        typer.Option(
            "--split-manifest", exists=True, dir_okay=False, readable=True, resolve_path=True
        ),
    ],
    split_content_manifest: Annotated[
        Path,
        typer.Option(
            "--split-content-manifest",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    config: Annotated[
        Path,
        typer.Option("--config", exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", file_okay=False, resolve_path=True),
    ],
) -> None:
    """Fit a Majority or Logistic baseline from a verified Train-only cache."""

    try:
        result = train_cached_model(
            feature_manifest=feature_manifest,
            split_manifest=split_manifest,
            split_content_manifest=split_content_manifest,
            config_path=config,
            output_dir=output_dir,
        )
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Model: {result.model_path}")
    typer.echo(f"Training manifest: {result.manifest_path}")


@evaluate_app.command("run")
def evaluate_run(
    run_dir: Annotated[
        Path,
        typer.Option("--run-dir", exists=True, file_okay=False, readable=True, resolve_path=True),
    ],
) -> None:
    """Verify a completed Validation prediction and metric bundle."""

    try:
        result = verify_evaluation_run(run_dir)
    except (OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Verified {result.artifact_count} Validation artifacts")
    typer.echo(f"Metrics: {result.metrics_path}")


@experiment_app.command("run")
def experiment_run(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Frozen Validation experiment YAML configuration.",
        ),
    ],
    split: Annotated[
        Literal["random", "cluster70", "cluster50", "cluster30"],
        typer.Option("--split", help="Frozen split to evaluate."),
    ],
    baseline: Annotated[
        Literal[
            "majority",
            "length_logistic",
            "aac_logistic",
            "kmer3_logistic",
            "nearest_homolog",
        ],
        typer.Option("--baseline", help="Frozen classical baseline to evaluate."),
    ],
) -> None:
    """Run one Train-to-Validation experiment cell."""

    try:
        result = run_experiment_cell(config, split, baseline)
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Completed {result.split_name}/{result.baseline_name} on Validation")
    typer.echo(f"Run directory: {result.run_dir}")
    typer.echo(f"Manifest SHA-256: {result.manifest_sha256}")


@experiment_app.command("matrix")
def experiment_matrix(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Frozen Validation experiment YAML configuration.",
        ),
    ],
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Verify and reuse byte-complete cells; reject any mismatch.",
        ),
    ] = False,
) -> None:
    """Run the fixed five-baseline by four-split Validation matrix."""

    try:
        result = run_matrix(config, resume=resume)
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Completed {len(result.cells)} Validation cells")
    typer.echo(f"Matrix summary: {result.summary_path}")


@experiment_app.command("replay-compare")
def experiment_replay_compare(
    first: Annotated[
        Path,
        typer.Option("--first", exists=True, file_okay=False, readable=True, resolve_path=True),
    ],
    second: Annotated[
        Path,
        typer.Option("--second", exists=True, file_okay=False, readable=True, resolve_path=True),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", dir_okay=False, resolve_path=True),
    ],
) -> None:
    """Compare deterministic content from two Validation matrix replays."""

    try:
        report = compare_validation_replays(first, second, output)
    except (FileExistsError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Compared {report.compared_file_count} deterministic artifacts")
    typer.echo(f"Byte identical: {'yes' if report.byte_identical else 'no'}")
    typer.echo(f"Report: {report.output_path}")
    if not report.byte_identical:
        raise typer.Exit(code=1)


@experiment_app.command("summarize")
def experiment_summarize(
    matrix_dir: Annotated[
        Path,
        typer.Option(
            "--matrix-dir", exists=True, file_okay=False, readable=True, resolve_path=True
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", file_okay=False, resolve_path=True),
    ],
) -> None:
    """Create a sequence-free aggregate preview from a verified Validation matrix."""

    try:
        result = write_validation_aggregates(matrix_dir, output_dir)
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Wrote {len(result.paths)} Validation aggregate files")
    typer.echo(f"Summary: {result.summary_path}")


@experiment_app.command("finalize-test")
def experiment_finalize_test(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Denied Test experiment YAML configuration.",
        ),
    ],
) -> None:
    """Enforce the v0.3 real-Test authorization gate before opening inputs."""

    try:
        experiment = load_experiment_config(config)
        if experiment.evaluation.split != "test" or experiment.attestation is None:
            raise RealTestAccessDenied(
                "Real test access is not authorized by the active attestation"
            )
        enforce_test_gate(experiment.attestation)
        raise RealTestAccessDenied("Real test access is not authorized by the active attestation")
    except RealTestAccessDenied as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=1) from error
    except (OSError, ValueError) as error:
        typer.echo(f"Error: invalid Test gate configuration: {error}", err=True)
        raise typer.Exit(code=2) from error


def main() -> None:
    """Console-script entry point."""

    app()


if __name__ == "__main__":
    main()
