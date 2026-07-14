# SPDX-License-Identifier: Apache-2.0

"""Command-line interface for project-foundation diagnostics."""

from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer

from protein_split_audit import __version__
from protein_split_audit.config import load_build_config, load_download_config
from protein_split_audit.data.build_candidates import BuildError, build_candidate_dataset
from protein_split_audit.data.download_uniprot import DownloadError, download_uniprot
from protein_split_audit.data.profile import ProfileError, profile_candidate_dataset
from protein_split_audit.paths import find_project_root, is_writable_directory
from protein_split_audit.provenance import git_metadata

app = typer.Typer(
    add_completion=False,
    help="Foundation diagnostics for ProteinSplitAudit.",
    invoke_without_command=True,
    no_args_is_help=True,
)
data_app = typer.Typer(help="Source-data commands.", no_args_is_help=True)
app.add_typer(data_app, name="data")


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


def run_doctor(start: Path | None = None) -> list[DoctorCheck]:
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

    checks.extend(
        [
            DoctorCheck(
                "MMseqs2 (future, optional)",
                "INFO",
                shutil.which("mmseqs") or "not installed",
                required=False,
            ),
            DoctorCheck(
                "PyTorch (future, optional)",
                "INFO",
                "available" if importlib.util.find_spec("torch") else "not installed",
                required=False,
            ),
        ]
    )
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
def doctor() -> None:
    """Check the local project foundation without network access."""

    checks = run_doctor()
    for check in checks:
        typer.echo(f"[{check.status}] {check.name}: {check.detail}")

    failed = any(check.required and check.status == "FAIL" for check in checks)
    typer.echo(f"Overall: {'FAIL' if failed else 'PASS'}")
    if failed:
        raise typer.Exit(code=1)


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


def main() -> None:
    """Console-script entry point."""

    app()


if __name__ == "__main__":
    main()
