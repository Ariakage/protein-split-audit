# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from protein_split_audit.similarity.commands import (
    ClusterCommandPaths,
    SearchCommandPaths,
    build_audit_argv,
    build_cluster_argv,
    build_self_search_argv,
)
from protein_split_audit.similarity.mmseqs import (
    MmseqsProbeError,
    MmseqsRunContext,
    MmseqsRunError,
    MmseqsTool,
    probe_mmseqs,
    run_mmseqs,
)
from protein_split_audit.similarity.schemas import (
    AuditSearchParameters,
    ClusterParameters,
    MmseqsRuntimeConfig,
    SelfSearchParameters,
)


def _runtime(cache_root: Path) -> MmseqsRuntimeConfig:
    return MmseqsRuntimeConfig(
        executable="mmseqs",
        cache_root=cache_root,
        timeout_seconds=3600,
        threads=8,
    )


def _write_fake_mmseqs(directory: Path, *, version: str = "18-8cc5c") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "mmseqs"
    executable.write_text(
        f"#!/bin/sh\nprintf '%s\\n' 'MMseqs2 Version: {version}'\n",
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o700)
    return executable


def _cluster_parameters(identity: float = 0.30) -> ClusterParameters:
    return ClusterParameters(
        sensitivity=7.5,
        evalue=0.001,
        sequence_identity_mode=0,
        min_sequence_identity=identity,
        minimum_coverage=0.80,
        coverage_mode=0,
        alignment_mode=3,
        cluster_mode=0,
        cluster_reassign=True,
    )


def _self_search_parameters() -> SelfSearchParameters:
    return SelfSearchParameters(
        sensitivity=7.5,
        evalue=0.001,
        search_type=1,
        sequence_identity_mode=0,
        min_sequence_identity=0.30,
        minimum_coverage=0.80,
        coverage_mode=0,
        alignment_mode=3,
        format_mode=4,
    )


def _audit_search_parameters() -> AuditSearchParameters:
    return AuditSearchParameters(
        sensitivity=7.5,
        evalue=0.001,
        search_type=1,
        sequence_identity_mode=0,
        min_sequence_identity=0.0,
        minimum_coverage=0.80,
        coverage_mode=0,
        alignment_mode=3,
        format_mode=4,
    )


def _search_argv_for_run(run: MmseqsRunContext, tmp_path: Path) -> Sequence[str]:
    paths = SearchCommandPaths(
        query_fasta=tmp_path / "input.fasta",
        target_fasta=tmp_path / "input.fasta",
        output_tsv=run.expected_outputs[0],
        temp_dir=run.staging_dir / "tmp",
    )
    return build_self_search_argv(
        _self_search_parameters(), _runtime(run.cache_root), 2, paths=paths
    )


class _RecordingProbe:
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self.calls: list[tuple[str, float]] = []

    def __call__(self, executable: str, *, timeout_seconds: float) -> MmseqsTool:
        self.calls.append((executable, timeout_seconds))
        return MmseqsTool(executable=self.executable, version="18-8cc5c")


class _FailingProbe:
    def __call__(self, executable: str, *, timeout_seconds: float) -> MmseqsTool:
        raise MmseqsProbeError(f"MMseqs2 executable not found: {executable} ({timeout_seconds:g}s)")


class _SuccessfulExecutor:
    def __init__(self) -> None:
        self.argv: tuple[str, ...] | None = None
        self.kwargs: dict[str, Any] = {}

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.argv = tuple(argv)
        self.kwargs = kwargs
        Path(argv[4]).write_text("query\ttarget\n", encoding="utf-8", newline="\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="warning\n")


class _SuccessfulClusterExecutor:
    def __call__(self, argv: Sequence[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        Path(f"{argv[3]}_cluster.tsv").write_text(
            "representative\tmember\n", encoding="utf-8", newline="\n"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class _UnexpectedExecutor:
    def __init__(self) -> None:
        self.called = False

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.called = True
        raise AssertionError(f"executor must not be called: {argv!r}, {kwargs!r}")


class _ReturningExecutor:
    def __init__(self, *, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls = 0

    def __call__(self, argv: Sequence[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr=self.stderr)


class _SymlinkOutputExecutor:
    def __init__(self, target: Path) -> None:
        self.target = target

    def __call__(self, argv: Sequence[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        Path(argv[4]).symlink_to(self.target)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class _TimeoutExecutor:
    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        staging_dir = kwargs["cwd"]
        assert isinstance(staging_dir, Path)
        (staging_dir / "partial.tsv").write_text("partial\n", encoding="utf-8", newline="\n")
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stderr="slow command\n")


class _OSErrorExecutor:
    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        staging_dir = kwargs["cwd"]
        assert isinstance(staging_dir, Path)
        (staging_dir / "partial.db").mkdir()
        raise OSError("private host path must not enter the public error")


def test_build_cluster_argv_has_exact_fixed_parameter_order(tmp_path: Path) -> None:
    paths = ClusterCommandPaths(
        input_fasta=tmp_path / "input.fasta",
        output_prefix=tmp_path / "stage/cluster30",
        temp_dir=tmp_path / "stage/tmp",
    )

    argv = build_cluster_argv(
        _cluster_parameters(),
        _runtime(tmp_path / "cache"),
        17,
        paths=paths,
    )

    assert argv == (
        "mmseqs",
        "easy-cluster",
        str(paths.input_fasta),
        str(paths.output_prefix),
        str(paths.temp_dir),
        "--min-seq-id",
        "0.30",
        "-c",
        "0.80",
        "--cov-mode",
        "0",
        "--alignment-mode",
        "3",
        "--seq-id-mode",
        "0",
        "--cluster-mode",
        "0",
        "--cluster-reassign",
        "1",
        "--max-seqs",
        "17",
        "-s",
        "7.5",
        "-e",
        "0.001",
        "--threads",
        "8",
    )


def test_build_self_search_argv_has_exact_format_and_parameter_order(tmp_path: Path) -> None:
    paths = SearchCommandPaths(
        query_fasta=tmp_path / "cohort.fasta",
        target_fasta=tmp_path / "cohort.fasta",
        output_tsv=tmp_path / "stage/pairs.tsv",
        temp_dir=tmp_path / "stage/tmp",
    )

    argv = build_self_search_argv(
        _self_search_parameters(),
        _runtime(tmp_path / "cache"),
        23,
        paths=paths,
    )

    assert argv == (
        "mmseqs",
        "easy-search",
        str(paths.query_fasta),
        str(paths.target_fasta),
        str(paths.output_tsv),
        str(paths.temp_dir),
        "--search-type",
        "1",
        "--min-seq-id",
        "0.30",
        "-c",
        "0.80",
        "--cov-mode",
        "0",
        "--alignment-mode",
        "3",
        "--seq-id-mode",
        "0",
        "--max-seqs",
        "23",
        "-s",
        "7.5",
        "-e",
        "0.001",
        "--format-mode",
        "4",
        "--format-output",
        "query,target,fident,qcov,tcov,evalue,bits",
        "--threads",
        "8",
    )


def test_build_audit_argv_uses_zero_identity_and_verified_train_count(tmp_path: Path) -> None:
    paths = SearchCommandPaths(
        query_fasta=tmp_path / "test.fasta",
        target_fasta=tmp_path / "train.fasta",
        output_tsv=tmp_path / "stage/audit.tsv",
        temp_dir=tmp_path / "stage/tmp",
    )

    argv = build_audit_argv(
        _audit_search_parameters(),
        _runtime(tmp_path / "cache"),
        11,
        paths=paths,
    )

    assert argv[0:6] == (
        "mmseqs",
        "easy-search",
        str(paths.query_fasta),
        str(paths.target_fasta),
        str(paths.output_tsv),
        str(paths.temp_dir),
    )
    assert argv[argv.index("--min-seq-id") + 1] == "0.0"
    assert argv[argv.index("--max-seqs") + 1] == "11"
    assert argv[argv.index("--format-output") + 1] == ("query,target,fident,qcov,tcov,evalue,bits")


@pytest.mark.parametrize("operation", ["cluster", "self-search", "audit"])
@pytest.mark.parametrize("count", [0, -1, True, 1.5])
def test_builders_reject_nonpositive_verified_counts(
    tmp_path: Path, operation: str, count: Any
) -> None:
    runtime = _runtime(tmp_path / "cache")
    if operation == "cluster":
        with pytest.raises(ValueError, match="positive"):
            build_cluster_argv(
                _cluster_parameters(),
                runtime,
                count,
                paths=ClusterCommandPaths(
                    tmp_path / "input.fasta", tmp_path / "stage/output", tmp_path / "stage/tmp"
                ),
            )
    else:
        paths = SearchCommandPaths(
            tmp_path / "query.fasta",
            tmp_path / "target.fasta",
            tmp_path / "stage/output.tsv",
            tmp_path / "stage/tmp",
        )
        with pytest.raises(ValueError, match="positive"):
            if operation == "self-search":
                build_self_search_argv(_self_search_parameters(), runtime, count, paths=paths)
            else:
                build_audit_argv(_audit_search_parameters(), runtime, count, paths=paths)


def test_run_mmseqs_uses_injected_executor_without_a_shell(tmp_path: Path) -> None:
    cache_root = (tmp_path / "configured/cache/mmseqs").resolve()
    tool_path = (tmp_path / "bin/mmseqs").resolve()
    probe = _RecordingProbe(tool_path)
    executor = _SuccessfulExecutor()
    run = MmseqsRunContext.create(
        cache_root=cache_root,
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=probe,
        executor=executor,
    )
    paths = SearchCommandPaths(
        query_fasta=tmp_path / "input.fasta",
        target_fasta=tmp_path / "input.fasta",
        output_tsv=run.expected_outputs[0],
        temp_dir=run.staging_dir / "tmp",
    )
    argv = build_self_search_argv(_self_search_parameters(), _runtime(cache_root), 2, paths=paths)

    result = run_mmseqs(argv, run)

    assert result.returncode == 0
    assert result.mmseqs_version == "18-8cc5c"
    assert result.resolved_executable == tool_path
    assert result.sanitized_argv[0:6] == (
        "mmseqs",
        "easy-search",
        "<query_fasta>",
        "<target_fasta>",
        "<output_tsv>",
        "<temp_dir>",
    )
    assert str(tmp_path) not in " ".join(result.sanitized_argv)
    assert executor.argv is not None
    assert executor.argv[0] == str(tool_path)
    assert executor.kwargs["shell"] is False
    assert executor.kwargs["check"] is False
    assert executor.kwargs["encoding"] == "utf-8"
    assert executor.kwargs["errors"] == "replace"
    assert executor.kwargs["timeout"] == 5.0
    assert executor.kwargs["cwd"] == run.staging_dir
    assert result.outputs == run.expected_outputs
    assert run.expected_outputs[0].is_file()
    assert probe.calls == [("mmseqs", 10.0)]


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("inf")])
def test_run_context_rejects_nonfinite_or_nonpositive_timeout_before_staging(
    tmp_path: Path, timeout_seconds: float
) -> None:
    cache_root = (tmp_path / "cache/mmseqs").resolve()

    with pytest.raises(ValueError, match="timeout"):
        MmseqsRunContext.create(
            cache_root=cache_root,
            timeout_seconds=timeout_seconds,
            expected_output_names=("pairs.tsv",),
        )

    assert not cache_root.exists()


@pytest.mark.parametrize(
    "output_names",
    [(), ("",), ("../escape.tsv",), ("/absolute.tsv",), ("pairs.tsv", "pairs.tsv")],
)
def test_run_context_rejects_unsafe_empty_or_duplicate_output_names_before_staging(
    tmp_path: Path, output_names: tuple[str, ...]
) -> None:
    cache_root = (tmp_path / "cache/mmseqs").resolve()

    with pytest.raises(ValueError, match="output"):
        MmseqsRunContext.create(
            cache_root=cache_root,
            timeout_seconds=5.0,
            expected_output_names=output_names,
        )

    assert not cache_root.exists()


def test_run_context_rejects_single_string_instead_of_output_name_sequence(
    tmp_path: Path,
) -> None:
    cache_root = (tmp_path / "cache/mmseqs").resolve()

    with pytest.raises(ValueError, match="output"):
        MmseqsRunContext.create(
            cache_root=cache_root,
            timeout_seconds=5.0,
            expected_output_names="out",
        )

    assert not cache_root.exists()


def test_run_mmseqs_refuses_existing_completed_output_before_probe_or_execution(
    tmp_path: Path,
) -> None:
    completed_output = (tmp_path / "results/pairs.parquet").resolve()
    completed_output.parent.mkdir(parents=True)
    completed_output.write_text("released\n", encoding="utf-8", newline="\n")
    probe = _RecordingProbe((tmp_path / "bin/mmseqs").resolve())
    executor = _UnexpectedExecutor()
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        completed_outputs=(completed_output,),
        probe=probe,
        executor=executor,
    )

    with pytest.raises(MmseqsRunError, match="already exists"):
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert completed_output.read_text(encoding="utf-8") == "released\n"
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []
    assert probe.calls == []
    assert executor.called is False


def test_run_mmseqs_reports_nonzero_exit_before_missing_output_and_cleans_stage(
    tmp_path: Path,
) -> None:
    executor = _ReturningExecutor(returncode=7, stderr="command failed\n")
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=executor,
    )

    with pytest.raises(MmseqsRunError, match="status 7") as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert caught.value.returncode == 7
    assert caught.value.timed_out is False
    assert caught.value.stderr_tail == "command failed"
    assert caught.value.mmseqs_version == "18-8cc5c"
    assert caught.value.sanitized_argv[2:6] == (
        "<query_fasta>",
        "<target_fasta>",
        "<output_tsv>",
        "<temp_dir>",
    )
    assert str(tmp_path) not in " ".join(caught.value.sanitized_argv)
    assert caught.value.cleanup_succeeded is True
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []
    assert executor.calls == 1


def test_run_mmseqs_rejects_missing_expected_output_and_cleans_stage(tmp_path: Path) -> None:
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_ReturningExecutor(returncode=0),
    )

    with pytest.raises(MmseqsRunError, match="expected staged output") as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert caught.value.returncode == 0
    assert caught.value.cleanup_succeeded is True
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []


def test_run_mmseqs_rejects_expected_output_symlink_outside_stage(tmp_path: Path) -> None:
    outside_output = tmp_path / "outside/pairs.tsv"
    outside_output.parent.mkdir(parents=True)
    outside_output.write_text("external\n", encoding="utf-8", newline="\n")
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_SymlinkOutputExecutor(outside_output),
    )

    with pytest.raises(MmseqsRunError, match="expected staged output") as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert caught.value.returncode == 0
    assert caught.value.cleanup_succeeded is True
    assert outside_output.read_text(encoding="utf-8") == "external\n"
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []


def test_run_mmseqs_converts_timeout_and_cleans_partial_stage(tmp_path: Path) -> None:
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=0.25,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_TimeoutExecutor(),
    )

    with pytest.raises(MmseqsRunError, match="timed out") as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert caught.value.returncode is None
    assert caught.value.timed_out is True
    assert caught.value.stderr_tail == "slow command"
    assert caught.value.cleanup_succeeded is True
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []


def test_run_mmseqs_converts_os_error_without_leaking_details_and_cleans_stage(
    tmp_path: Path,
) -> None:
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_OSErrorExecutor(),
    )

    with pytest.raises(MmseqsRunError, match="could not be started") as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert "private host path" not in str(caught.value)
    assert caught.value.stderr_tail == ""
    assert caught.value.cleanup_succeeded is True
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []


def test_run_mmseqs_bounds_and_redacts_stderr(tmp_path: Path) -> None:
    stderr = (
        "x" * 200
        + "\x00\nAuthorization: Bearer top-secret\n"
        + "Cookie: session=private-cookie\n"
        + "password=hunter2\n"
        + "diagnostic tail\n"
    )
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        stderr_limit_chars=120,
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_ReturningExecutor(returncode=9, stderr=stderr),
    )

    with pytest.raises(MmseqsRunError) as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    tail = caught.value.stderr_tail
    assert len(tail) <= 120
    assert "top-secret" not in tail
    assert "private-cookie" not in tail
    assert "hunter2" not in tail
    assert "\x00" not in tail
    assert "<redacted>" in tail
    assert tail.endswith("diagnostic tail")


def test_run_mmseqs_redacts_prefixed_secret_keys_but_preserves_ordinary_stderr(
    tmp_path: Path,
) -> None:
    stderr = (
        "API_TOKEN=private-api-value\n"
        "GH_TOKEN: private-gh-value\n"
        "CI-TOKEN: private-ci-value\n"
        "MY_PASSWORD=private-password-value\n"
        "AWS_SECRET_ACCESS_KEY=private-aws-value\n"
        "PASSWORD_FILE=private-password-file\n"
        "tokenizer=sentencepiece\n"
        "token count remains 3\n"
    )
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_ReturningExecutor(returncode=9, stderr=stderr),
    )

    with pytest.raises(MmseqsRunError) as caught:
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    tail = caught.value.stderr_tail
    assert "private-api-value" not in tail
    assert "private-gh-value" not in tail
    assert "private-ci-value" not in tail
    assert "private-password-value" not in tail
    assert "private-aws-value" not in tail
    assert "private-password-file" not in tail
    assert tail.count("<redacted>") == 6
    assert "tokenizer=sentencepiece" in tail
    assert "token count remains 3" in tail


def test_metacharacters_remain_one_literal_argument_and_never_reach_a_shell(tmp_path: Path) -> None:
    executor = _SuccessfulExecutor()
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=executor,
    )
    query = tmp_path / "input; touch SHOULD_NOT_EXIST.fasta"
    paths = SearchCommandPaths(query, query, run.expected_outputs[0], run.staging_dir / "tmp")
    argv = build_self_search_argv(
        _self_search_parameters(), _runtime(run.cache_root), 2, paths=paths
    )

    run_mmseqs(argv, run)

    assert executor.argv is not None
    assert executor.argv[2] == str(query)
    assert executor.kwargs["shell"] is False
    assert not (tmp_path / "SHOULD_NOT_EXIST.fasta").exists()


def test_run_context_creates_unique_children_under_configured_cache_and_is_immutable(
    tmp_path: Path,
) -> None:
    cache_root = (tmp_path / "from-config/cache/mmseqs").resolve()
    first = MmseqsRunContext.create(
        cache_root=cache_root,
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
    )
    second = MmseqsRunContext.create(
        cache_root=cache_root,
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
    )

    assert first.staging_dir.parent == cache_root
    assert second.staging_dir.parent == cache_root
    assert first.staging_dir != second.staging_dir
    with pytest.raises(FrozenInstanceError):
        first.timeout_seconds = 1.0


def test_probe_mmseqs_reports_missing_executable_without_running_a_real_tool(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(MmseqsProbeError, match="not found"):
        probe_mmseqs("missing-mmseqs-task3")


def test_probe_mmseqs_parses_version_from_tmp_path_fake_executable(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin")

    tool = probe_mmseqs(str(executable))

    assert tool == MmseqsTool(executable=executable.resolve(), version="18-8cc5c")


def test_probe_mmseqs_rejects_unexecutable_tmp_path_file(tmp_path: Path) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin")
    executable.chmod(0o600)

    with pytest.raises(MmseqsProbeError, match="not found"):
        probe_mmseqs(str(executable))


def test_run_context_rejects_relative_cache_root_without_using_process_cwd(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="cache_root"):
        MmseqsRunContext.create(
            cache_root=Path("cache/mmseqs"),
            timeout_seconds=5.0,
            expected_output_names=("pairs.tsv",),
        )

    assert not (tmp_path / "cache/mmseqs").exists()


def test_run_context_rejects_relative_completed_output_before_staging(tmp_path: Path) -> None:
    cache_root = (tmp_path / "cache/mmseqs").resolve()

    with pytest.raises(ValueError, match="completed output"):
        MmseqsRunContext.create(
            cache_root=cache_root,
            timeout_seconds=5.0,
            expected_output_names=("pairs.tsv",),
            completed_outputs=(Path("relative.parquet"),),
        )

    assert not cache_root.exists()


def test_run_context_rejects_secret_bearing_environment_before_staging(tmp_path: Path) -> None:
    cache_root = (tmp_path / "cache/mmseqs").resolve()

    with pytest.raises(ValueError, match="environment"):
        MmseqsRunContext.create(
            cache_root=cache_root,
            timeout_seconds=5.0,
            expected_output_names=("pairs.tsv",),
            environment={"PATH": "/bin", "AUTHORIZATION": "Bearer secret"},
        )

    assert not cache_root.exists()


def test_probe_mmseqs_does_not_inherit_secret_environment(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    executable = _write_fake_mmseqs(tmp_path / "bin")
    executable.write_text(
        "#!/bin/sh\n"
        'if [ "${AUTHORIZATION+x}" = x ]; then exit 9; fi\n'
        "printf '%s\\n' 'MMseqs2 Version: 18-8cc5c'\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setenv("AUTHORIZATION", "Bearer private-token")

    tool = probe_mmseqs(str(executable))

    assert tool.version == "18-8cc5c"


@pytest.mark.parametrize("escaped_field", ["output", "temp"])
def test_run_mmseqs_refuses_output_or_temp_path_outside_unique_stage(
    tmp_path: Path, escaped_field: str
) -> None:
    probe = _RecordingProbe((tmp_path / "bin/mmseqs").resolve())
    executor = _UnexpectedExecutor()
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=probe,
        executor=executor,
    )
    outside_output = (tmp_path / "outside/pairs.tsv").resolve()
    outside_temp = (tmp_path / "outside/tmp").resolve()
    paths = SearchCommandPaths(
        query_fasta=tmp_path / "input.fasta",
        target_fasta=tmp_path / "input.fasta",
        output_tsv=outside_output if escaped_field == "output" else run.expected_outputs[0],
        temp_dir=outside_temp if escaped_field == "temp" else run.staging_dir / "tmp",
    )
    argv = build_self_search_argv(
        _self_search_parameters(), _runtime(run.cache_root), 2, paths=paths
    )

    with pytest.raises(MmseqsRunError, match="staging path"):
        run_mmseqs(argv, run)

    assert not outside_output.exists()
    assert not outside_temp.exists()
    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []
    assert probe.calls == []
    assert executor.called is False


def test_run_mmseqs_accepts_cluster_prefix_with_expected_cluster_tsv(tmp_path: Path) -> None:
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("cluster30_cluster.tsv",),
        probe=_RecordingProbe((tmp_path / "bin/mmseqs").resolve()),
        executor=_SuccessfulClusterExecutor(),
    )
    paths = ClusterCommandPaths(
        input_fasta=tmp_path / "input.fasta",
        output_prefix=run.staging_dir / "cluster30",
        temp_dir=run.staging_dir / "tmp",
    )
    argv = build_cluster_argv(_cluster_parameters(), _runtime(run.cache_root), 2, paths=paths)

    result = run_mmseqs(argv, run)

    assert result.outputs == (run.staging_dir / "cluster30_cluster.tsv",)
    assert result.sanitized_argv[0:5] == (
        "mmseqs",
        "easy-cluster",
        "<input_fasta>",
        "<output_prefix>",
        "<temp_dir>",
    )


def test_command_path_contexts_reject_relative_paths(tmp_path: Path) -> None:
    absolute = tmp_path.resolve()

    with pytest.raises(ValueError, match="absolute"):
        ClusterCommandPaths(Path("input.fasta"), absolute / "output", absolute / "tmp")
    with pytest.raises(ValueError, match="absolute"):
        SearchCommandPaths(
            absolute / "query.fasta",
            absolute / "target.fasta",
            Path("output.tsv"),
            absolute / "tmp",
        )


def test_run_mmseqs_probe_failure_leaves_only_empty_unique_stage(tmp_path: Path) -> None:
    executor = _UnexpectedExecutor()
    run = MmseqsRunContext.create(
        cache_root=(tmp_path / "cache/mmseqs").resolve(),
        timeout_seconds=5.0,
        expected_output_names=("pairs.tsv",),
        probe=_FailingProbe(),
        executor=executor,
    )

    with pytest.raises(MmseqsProbeError, match="not found"):
        run_mmseqs(_search_argv_for_run(run, tmp_path), run)

    assert run.staging_dir.is_dir()
    assert list(run.staging_dir.iterdir()) == []
    assert executor.called is False
