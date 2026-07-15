# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import shlex
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from rich.text import Text
from typer.testing import CliRunner

from protein_split_audit import __version__
from protein_split_audit.cli import app
from tests.test_build_candidates import run_build

runner = CliRunner()
colored_terminal = {"TERM": "xterm-256color", "FORCE_COLOR": "1"}
PROJECT_ROOT = Path(__file__).parents[1]


def _write_fake_mmseqs(
    directory: Path,
    *,
    version_output: str = "18-8cc5c",
    delay_seconds: float | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "mmseqs"
    lines = ["#!/bin/sh", 'test "$1" = "version" || exit 64']
    if delay_seconds is not None:
        lines.append(f"sleep {delay_seconds}")
    lines.append(f"printf '%s\\n' {shlex.quote(version_output)}")
    executable.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    executable.chmod(0o755)
    return executable


def _candidate_discovery_config(
    tmp_path: Path,
    *,
    executable: str,
    cache_root: str = "../cache/mmseqs",
) -> Path:
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, Any] = {
        "schema_version": 1,
        "operation": "candidate_discovery",
        "name": "candidate-pool-cluster30",
        "run_mode": "development",
        "runtime": {
            "executable": executable,
            "cache_root": cache_root,
            "timeout_seconds": 1.0,
            "threads": 1,
        },
        "self_search": {
            "sensitivity": 7.5,
            "evalue": 0.001,
            "search_type": 1,
            "sequence_identity_mode": 0,
            "min_sequence_identity": 0.30,
            "minimum_coverage": 0.80,
            "coverage_mode": 0,
            "alignment_mode": 3,
            "format_mode": 4,
        },
        "input": {
            "candidate_dataset": "../inputs/pilot.parquet",
            "build_manifest": "../inputs/pilot.build.json",
            "fasta": "../inputs/pilot.fasta",
        },
        "output": {
            "component_manifest": "../outputs/components.parquet",
            "content_manifest": "../outputs/components.json",
            "pair_table": "../outputs/pairs.parquet",
            "run_dir": "../runs/discovery",
            "overwrite": False,
        },
    }
    config_path = config_dir / "similarity.yaml"
    config_path.write_text(
        yaml.safe_dump(mapping, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return config_path


def _cohort_cluster_base_config(tmp_path: Path) -> Path:
    config_path = _candidate_discovery_config(tmp_path, executable="mmseqs")
    mapping = yaml.safe_load(config_path.read_bytes())
    assert isinstance(mapping, dict)
    mapping["operation"] = "cohort_cluster_base"
    mapping["name"] = "cluster30"
    mapping["cluster"] = {
        "sensitivity": 7.5,
        "evalue": 0.001,
        "sequence_identity_mode": 0,
        "min_sequence_identity": 0.30,
        "minimum_coverage": 0.80,
        "coverage_mode": 0,
        "alignment_mode": 3,
        "cluster_mode": 0,
        "cluster_reassign": True,
    }
    mapping["input"] = {
        "cohort_manifest": "../inputs/cohort.parquet",
        "cohort_content_manifest": "../inputs/cohort.json",
        "fasta": "../inputs/cohort.fasta",
    }
    mapping["output"] = {
        "cluster_manifest": "../outputs/cluster30.parquet",
        "content_manifest": "../outputs/cluster30.json",
        "pair_table": "../outputs/pairs.parquet",
        "run_dir": "../runs/cluster30",
        "overwrite": False,
    }
    config_path.write_text(
        yaml.safe_dump(mapping, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return config_path


@dataclass(frozen=True, slots=True)
class _CliDiscoveryResult:
    sequence_count: int = 2
    edge_count: int = 1
    component_count: int = 1
    singleton_count: int = 0
    largest_component_size: int = 2


def test_version_option_reports_installed_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_current_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "data" in result.stdout
    assert "cohort" in result.stdout
    assert "similarity" in result.stdout
    assert "split" in result.stdout
    assert "feature" in result.stdout
    assert "model" in result.stdout
    assert "evaluate" in result.stdout
    assert "experiment" in result.stdout
    assert "download" not in result.stdout
    assert "build" not in result.stdout
    assert "profile" not in result.stdout


def test_v030_experiment_commands_are_registered() -> None:
    matrix = runner.invoke(app, ["experiment", "matrix", "--help"])
    final = runner.invoke(app, ["experiment", "finalize-test", "--help"])

    assert matrix.exit_code == 0
    assert "--config" in Text.from_ansi(matrix.stdout).plain
    assert final.exit_code == 0
    assert "--config" in Text.from_ansi(final.stdout).plain


def test_v030_low_level_commands_are_registered() -> None:
    feature = runner.invoke(app, ["feature", "extract", "--help"])
    model = runner.invoke(app, ["model", "train", "--help"])
    evaluate = runner.invoke(app, ["evaluate", "run", "--help"])

    assert feature.exit_code == 0
    assert "--cohort-manifest" in Text.from_ansi(feature.stdout).plain
    assert model.exit_code == 0
    assert "--feature-manifest" in Text.from_ansi(model.stdout).plain
    assert evaluate.exit_code == 0
    assert "--run-dir" in Text.from_ansi(evaluate.stdout).plain


def test_v030_formal_test_command_denies_before_real_inputs() -> None:
    result = runner.invoke(
        app,
        [
            "experiment",
            "finalize-test",
            "--config",
            str(PROJECT_ROOT / "configs/experiment/v030-test.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "Real test access is not authorized by the active attestation" in result.stderr


def test_data_download_help_is_registered() -> None:
    result = runner.invoke(
        app,
        ["data", "download", "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "--config" in output
    assert "UniProt" in output


def test_data_build_help_is_registered() -> None:
    result = runner.invoke(
        app,
        ["data", "build", "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "--config" in output
    assert "candidate" in output.lower()


def test_data_profile_help_is_registered() -> None:
    result = runner.invoke(
        app,
        ["data", "profile", "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "--dataset" in output
    assert "--build-manifest" in output
    assert "--output-dir" in output
    assert "aggregate" in output.lower()


def test_doctor_succeeds_for_repository() -> None:
    result = runner.invoke(app, ["doctor"], env={"PATH": ""})

    assert result.exit_code == 0
    assert "ProteinSplitAudit version" in result.stdout
    assert "Python version" in result.stdout
    assert "Operating system" in result.stdout
    assert "Architecture" in result.stdout
    assert "Logical CPUs" in result.stdout
    assert "Project root" in result.stdout
    assert "uv.lock" in result.stdout
    assert "MMseqs2 cache writable" in result.stdout
    assert "[WARN] MMseqs2 executable" in result.stdout
    assert "Overall: PASS" in result.stdout


@pytest.mark.parametrize(
    ("group", "commands"),
    [
        ("cohort", ("profile", "select", "validate")),
        ("similarity", ("audit", "cluster", "validate")),
        ("split", ("create", "validate")),
    ],
)
def test_v020_subapp_help_lists_planned_commands(
    group: str,
    commands: tuple[str, ...],
) -> None:
    result = runner.invoke(
        app,
        [group, "--help"],
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "\x1b[" in result.stdout
    for command in commands:
        assert command in output


@pytest.mark.parametrize(
    ("arguments", "options"),
    [
        (
            ["cohort", "profile", "--help"],
            ("--dataset", "--build-manifest", "--fasta", "--output-dir"),
        ),
        (["cohort", "select", "--help"], ("--config",)),
        (
            ["cohort", "validate", "--help"],
            ("--manifest", "--content-manifest"),
        ),
        (["similarity", "cluster", "--help"], ("--config",)),
        (
            ["similarity", "validate", "--help"],
            ("--manifest", "--content-manifest"),
        ),
        (
            ["similarity", "audit", "--help"],
            ("--config",),
        ),
        (["split", "create", "--help"], ("--config",)),
        (["split", "validate", "--help"], ("--manifest", "--config")),
    ],
)
def test_v020_command_help_is_registered_and_colored(
    arguments: list[str],
    options: tuple[str, ...],
) -> None:
    result = runner.invoke(
        app,
        arguments,
        color=True,
        env=colored_terminal,
    )
    output = Text.from_ansi(result.stdout).plain

    assert result.exit_code == 0
    assert "\x1b[" in result.stdout
    for option in options:
        assert option in output


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "similarity",
            "validate",
            "--manifest",
            "unused.parquet",
            "--content-manifest",
            "unused.json",
        ],
        [
            "split",
            "validate",
            "--manifest",
            "unused.parquet",
            "--config",
            "unused.yaml",
        ],
    ],
)
def test_remaining_validation_commands_are_non_operational_placeholders(
    arguments: list[str],
) -> None:
    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert "not implemented in this task" in result.output


def test_cohort_select_runs_provisional_development_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cli as cli_module

    result_object = SimpleNamespace(
        selected_count=200,
        selected_labels=("1.1", "2.1", "3.1", "4.1", "5.1"),
        cohort_manifest=PROJECT_ROOT / "data/manifests/cohorts/pilot-v1-candidate.parquet",
        fasta=PROJECT_ROOT / "data/processed/cohorts/pilot-v1-candidate.fasta",
        content_manifest=PROJECT_ROOT / "data/manifests/cohorts/pilot-v1-candidate.json",
        content=SimpleNamespace(release_eligible=False),
    )
    monkeypatch.setattr(cli_module, "build_cohort", lambda *_args, **_kwargs: result_object)

    result = runner.invoke(
        app,
        ["cohort", "select", "--config", str(PROJECT_ROOT / "configs/cohort/pilot.yaml")],
    )

    assert result.exit_code == 0
    assert "Provisional cohort selected 200 candidates" in result.output
    assert "1.1, 2.1, 3.1, 4.1, 5.1" in result.output
    assert "Release eligible: no" in result.output


def test_cohort_select_reports_reviewed_frozen_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    import protein_split_audit.cli as cli_module

    result_object = SimpleNamespace(
        selected_count=442,
        selected_labels=("2.7", "3.1", "1.1", "2.1", "4.1"),
        cohort_manifest=PROJECT_ROOT / "data/manifests/cohorts/pilot-v1.parquet",
        fasta=PROJECT_ROOT / "data/processed/cohorts/pilot-v1.fasta",
        content_manifest=PROJECT_ROOT / "data/manifests/cohorts/pilot-v1.json",
        content=SimpleNamespace(release_eligible=True),
    )
    monkeypatch.setattr(cli_module, "build_cohort", lambda *_args, **_kwargs: result_object)

    result = runner.invoke(
        app,
        ["cohort", "select", "--config", str(PROJECT_ROOT / "configs/cohort/pilot-freeze.yaml")],
    )

    assert result.exit_code == 0
    assert "Frozen pilot-v1 selected 442 candidates" in result.output
    assert "Release eligible: yes" in result.output


def test_cohort_select_missing_config_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["cohort", "select", "--config", str(tmp_path / "missing.yaml")],
    )

    assert result.exit_code == 2
    assert "Invalid value for" in Text.from_ansi(result.output).plain


def test_cohort_validate_reports_recomputed_provisional_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cli as cli_module

    manifest = tmp_path / "cohort.parquet"
    content = tmp_path / "cohort.json"
    manifest.write_bytes(b"fixture")
    content.write_bytes(b"fixture")
    report = SimpleNamespace(
        selected_count=200,
        selected_labels=("1.1", "2.1", "3.1", "4.1", "5.1"),
        cohort_version="pilot-v1-candidate",
        provisional=True,
    )
    monkeypatch.setattr(cli_module, "find_project_root", lambda _path: tmp_path)
    monkeypatch.setattr(
        cli_module,
        "validate_cohort_artifacts",
        lambda *_args, **_kwargs: report,
    )

    result = runner.invoke(
        app,
        [
            "cohort",
            "validate",
            "--manifest",
            str(manifest),
            "--content-manifest",
            str(content),
        ],
    )

    assert result.exit_code == 0
    assert "Validated provisional cohort: 200 candidates" in result.output
    assert "1.1, 2.1, 3.1, 4.1, 5.1" in result.output


def test_cohort_validate_reports_recomputed_frozen_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cli as cli_module

    manifest = tmp_path / "pilot-v1.parquet"
    content = tmp_path / "pilot-v1.json"
    manifest.write_bytes(b"fixture")
    content.write_bytes(b"fixture")
    report = SimpleNamespace(
        selected_count=442,
        selected_labels=("2.7", "3.1", "1.1", "2.1", "4.1"),
        cohort_version="pilot-v1",
        provisional=False,
    )
    monkeypatch.setattr(cli_module, "find_project_root", lambda _path: tmp_path)
    monkeypatch.setattr(
        cli_module,
        "validate_cohort_artifacts",
        lambda *_args, **_kwargs: report,
    )

    result = runner.invoke(
        app,
        [
            "cohort",
            "validate",
            "--manifest",
            str(manifest),
            "--content-manifest",
            str(content),
        ],
    )

    assert result.exit_code == 0
    assert "Validated frozen pilot-v1: 442 candidates" in result.output
    assert "2.7, 3.1, 1.1, 2.1, 4.1" in result.output


def test_similarity_cluster_missing_config_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["similarity", "cluster", "--config", str(tmp_path / "missing.yaml")],
    )

    assert result.exit_code == 2
    assert "Invalid value for" in Text.from_ansi(result.output).plain


def test_similarity_cluster_malformed_config_is_usage_error(tmp_path: Path) -> None:
    config_path = tmp_path / "malformed.yaml"
    config_path.write_text("runtime: [\n", encoding="utf-8", newline="\n")

    result = runner.invoke(app, ["similarity", "cluster", "--config", str(config_path)])

    assert result.exit_code == 2
    assert "invalid similarity configuration" in result.output
    assert "invalid YAML configuration" in result.output


def test_similarity_cluster_dispatches_candidate_discovery_with_aggregate_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cli as cli_module

    config_path = _candidate_discovery_config(tmp_path, executable="mmseqs")
    captured: dict[str, object] = {}

    def fake_discovery(
        document: object,
        *,
        run_context_factory: object,
    ) -> _CliDiscoveryResult:
        captured["document"] = document
        captured["run_context_factory"] = run_context_factory
        return _CliDiscoveryResult()

    monkeypatch.setattr(cli_module, "discover_candidate_pool", fake_discovery)

    result = runner.invoke(app, ["similarity", "cluster", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "2 sequences" in result.output
    assert "1 normalized pair edge" in result.output
    assert "1 component" in result.output
    assert "0 singletons" in result.output
    assert "largest 2" in result.output
    assert "pair table, component manifest, and content manifest" in result.output
    assert "local run provenance" in result.output
    assert str(tmp_path) not in result.output
    assert "document" in captured
    assert captured["run_context_factory"] is cli_module.create_discovery_run_context


def test_similarity_cluster_runtime_failure_is_exit_one_and_path_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cli as cli_module
    from protein_split_audit.similarity.discovery import DiscoveryError

    config_path = _candidate_discovery_config(tmp_path, executable="mmseqs")

    def fail_discovery(*_args: object, **_kwargs: object) -> None:
        raise DiscoveryError("MMseqs2 candidate discovery execution failed")

    monkeypatch.setattr(cli_module, "discover_candidate_pool", fail_discovery)

    result = runner.invoke(app, ["similarity", "cluster", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Error: MMseqs2 candidate discovery execution failed" in result.output
    assert str(tmp_path) not in result.output


def test_similarity_cluster_dispatches_formal_base_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protein_split_audit.cli as cli_module

    config_path = _cohort_cluster_base_config(tmp_path)
    project_root = PROJECT_ROOT
    monkeypatch.setattr(cli_module, "find_project_root", lambda _path: project_root)
    result_object = SimpleNamespace(
        partition=SimpleNamespace(
            rows=(1, 2),
            node_to_component={"one": "component", "two": "component"},
        ),
        cluster_manifest_path=project_root / "data/manifests/similarity/cluster30.parquet",
        content_manifest_path=project_root / "data/manifests/similarity/cluster30.json",
    )
    monkeypatch.setattr(
        cli_module,
        "build_base_similarity",
        lambda *_args, **_kwargs: result_object,
    )

    result = runner.invoke(app, ["similarity", "cluster", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Generated cluster30: 2 sequences, 1 strict components" in result.output


def test_cohort_profile_writes_three_aggregate_outputs(tmp_path: Path) -> None:
    build, _source = run_build(tmp_path)
    output_dir = tmp_path / "results/cohort-profile"

    result = runner.invoke(
        app,
        [
            "cohort",
            "profile",
            "--dataset",
            str(build.parquet_path),
            "--build-manifest",
            str(build.manifest_path),
            "--fasta",
            str(build.fasta_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Profiled 2 candidates across 2 EC-level-2 classes" in result.output
    assert "Wrote 3 aggregate artifacts" in result.output
    assert {path.name for path in output_dir.iterdir()} == {
        "profile_summary.json",
        "ec_level_2_class_counts.csv",
        "sequence_length_summary.json",
    }
    content = b"".join(path.read_bytes() for path in output_dir.iterdir())
    assert str(tmp_path).encode() not in content
    assert b"A00001" not in content
    assert b"C00001" not in content
    assert b"A" * 50 not in content


def test_cohort_profile_missing_required_options_is_usage_error() -> None:
    result = runner.invoke(app, ["cohort", "profile"])

    assert result.exit_code == 2
    assert "Missing option" in result.output
    assert "--dataset" in Text.from_ansi(result.output).plain


@pytest.mark.parametrize("missing_input", ("dataset", "build_manifest", "fasta"))
def test_cohort_profile_missing_input_file_is_usage_error(
    tmp_path: Path,
    missing_input: str,
) -> None:
    build, _source = run_build(tmp_path)
    inputs = {
        "dataset": build.parquet_path,
        "build_manifest": build.manifest_path,
        "fasta": build.fasta_path,
    }
    inputs[missing_input] = tmp_path / f"missing-{missing_input}"

    result = runner.invoke(
        app,
        [
            "cohort",
            "profile",
            "--dataset",
            str(inputs["dataset"]),
            "--build-manifest",
            str(inputs["build_manifest"]),
            "--fasta",
            str(inputs["fasta"]),
            "--output-dir",
            str(tmp_path / "profile"),
        ],
    )

    assert result.exit_code == 2
    output = " ".join(Text.from_ansi(result.output).plain.split())
    assert "Invalid value for" in output
    assert "exist" in output


def test_cohort_profile_invalid_input_is_runtime_error(tmp_path: Path) -> None:
    build, _source = run_build(tmp_path)
    build.fasta_path.write_bytes(build.fasta_path.read_bytes() + b"tampered\n")

    result = runner.invoke(
        app,
        [
            "cohort",
            "profile",
            "--dataset",
            str(build.parquet_path),
            "--build-manifest",
            str(build.manifest_path),
            "--fasta",
            str(build.fasta_path),
            "--output-dir",
            str(tmp_path / "profile"),
        ],
    )

    assert result.exit_code == 1
    assert "Error: candidate FASTA hash does not match build manifest" in result.output


def test_cohort_profile_refuses_to_overwrite_outputs(tmp_path: Path) -> None:
    build, _source = run_build(tmp_path)
    output_dir = tmp_path / "profile"
    arguments = [
        "cohort",
        "profile",
        "--dataset",
        str(build.parquet_path),
        "--build-manifest",
        str(build.manifest_path),
        "--fasta",
        str(build.fasta_path),
        "--output-dir",
        str(output_dir),
    ]

    first = runner.invoke(app, arguments)
    before = (
        {path.name: path.read_bytes() for path in output_dir.iterdir()}
        if output_dir.exists()
        else {}
    )
    second = runner.invoke(app, arguments)

    assert first.exit_code == 0
    assert second.exit_code == 1
    assert "refusing to overwrite" in second.output
    assert {path.name: path.read_bytes() for path in output_dir.iterdir()} == before


def test_probe_mmseqs_uses_fake_executable_and_returns_version(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin")
    mmseqs_module = importlib.import_module("protein_split_audit.similarity.mmseqs")

    tool = mmseqs_module.probe_mmseqs(str(executable))

    assert tool.executable == executable.resolve()
    assert tool.version == "18-8cc5c"


def test_probe_mmseqs_enforces_timeout(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin", delay_seconds=1.0)
    mmseqs_module = importlib.import_module("protein_split_audit.similarity.mmseqs")

    with pytest.raises(RuntimeError, match="timed out"):
        mmseqs_module.probe_mmseqs(str(executable), timeout_seconds=0.01)


def test_doctor_uses_config_relative_mmseqs_and_cache_paths(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin")
    cache_root = tmp_path / "cache/mmseqs"
    cache_root.mkdir(parents=True)
    config_path = _candidate_discovery_config(
        tmp_path,
        executable="../bin/mmseqs",
    )

    result = runner.invoke(app, ["doctor", "--similarity-config", str(config_path)])

    assert result.exit_code == 0
    assert f"[PASS] MMseqs2 executable: {executable.resolve()}" in result.stdout
    assert "[PASS] MMseqs2 version: 18-8cc5c" in result.stdout
    assert f"[PASS] MMseqs2 cache writable: {cache_root.resolve()}" in result.stdout
    assert "Overall: PASS" in result.stdout


def test_doctor_warns_when_mmseqs_is_missing(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache/mmseqs"
    cache_root.mkdir(parents=True)
    config_path = _candidate_discovery_config(
        tmp_path,
        executable="missing-mmseqs-for-test",
    )

    result = runner.invoke(
        app,
        ["doctor", "--similarity-config", str(config_path)],
        env={"PATH": ""},
    )

    assert result.exit_code == 0
    assert "[WARN] MMseqs2 executable:" in result.stdout
    assert "[WARN] MMseqs2 version:" in result.stdout
    assert "Overall: PASS" in result.stdout


def test_doctor_warns_when_mmseqs_version_is_malformed(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin", version_output="not a version")
    (tmp_path / "cache/mmseqs").mkdir(parents=True)
    config_path = _candidate_discovery_config(tmp_path, executable=str(executable))

    result = runner.invoke(app, ["doctor", "--similarity-config", str(config_path)])

    assert result.exit_code == 0
    assert f"[PASS] MMseqs2 executable: {executable.resolve()}" in result.stdout
    assert "[WARN] MMseqs2 version:" in result.stdout
    assert "malformed" in result.stdout.lower()
    assert "Overall: PASS" in result.stdout


def test_doctor_fails_for_unwritable_mmseqs_cache_path(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin")
    cache_root = tmp_path / "cache-file"
    cache_root.write_text("not a directory\n", encoding="utf-8")
    config_path = _candidate_discovery_config(
        tmp_path,
        executable=str(executable),
        cache_root="../cache-file",
    )

    result = runner.invoke(app, ["doctor", "--similarity-config", str(config_path)])

    assert result.exit_code == 1
    assert f"[FAIL] MMseqs2 cache writable: {cache_root.resolve()}" in result.stdout
    assert "Overall: FAIL" in result.stdout


def test_doctor_reports_malformed_similarity_yaml_as_usage_error(tmp_path: Path) -> None:
    config_path = tmp_path / "malformed-similarity.yaml"
    config_path.write_text("runtime: [\n", encoding="utf-8", newline="\n")

    result = runner.invoke(app, ["doctor", "--similarity-config", str(config_path)])

    assert result.exit_code == 2
    assert "Error: invalid similarity configuration" in result.output
    assert "invalid YAML configuration" in result.output
