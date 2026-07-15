# SPDX-License-Identifier: Apache-2.0

"""Safe MMseqs2 discovery, staged execution, and local audit results."""

from __future__ import annotations

import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

_VERSION_PATTERN = re.compile(
    r"^(?:MMseqs2 Version:\s*)?(?P<version>[0-9]+(?:\.[0-9]+)*(?:-[0-9A-Za-z._-]+)?)$"
)
_SECRET_PATTERN = re.compile(
    r"(?im)(?<![A-Za-z0-9_-])"
    r"(?P<key>(?:[A-Za-z0-9]+[_-])*(?:authorization|cookie|token|password|secret)"
    r"(?:[_-][A-Za-z0-9]+)*)"
    r"\b\s*[:=]\s*[^\r\n]*"
)
_ALLOWED_ENVIRONMENT_NAMES = frozenset({"LANG", "LC_ALL", "PATH", "TMPDIR"})


@dataclass(frozen=True, slots=True)
class MmseqsTool:
    """One resolved MMseqs2 executable and its reported version."""

    executable: Path
    version: str


class MmseqsProbeError(RuntimeError):
    """Raised when MMseqs2 cannot be safely discovered or versioned."""

    def __init__(self, message: str, *, executable: Path | None = None) -> None:
        super().__init__(message)
        self.executable = executable


class MmseqsRunError(RuntimeError):
    """Raised when a staged MMseqs2 command cannot complete safely."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        timed_out: bool = False,
        stderr_tail: str = "",
        staging_dir: Path | None = None,
        cleanup_succeeded: bool = False,
        mmseqs_version: str | None = None,
        resolved_executable: Path | None = None,
        sanitized_argv: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.timed_out = timed_out
        self.stderr_tail = stderr_tail
        self.staging_dir = staging_dir
        self.cleanup_succeeded = cleanup_succeeded
        self.mmseqs_version = mmseqs_version
        self.resolved_executable = resolved_executable
        self.sanitized_argv = sanitized_argv


class MmseqsProbe(Protocol):
    """Callable contract for injected executable discovery/version probing."""

    def __call__(self, executable: str, *, timeout_seconds: float) -> MmseqsTool: ...


class MmseqsExecutor(Protocol):
    """Callable contract for injected subprocess execution."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        check: bool,
        shell: bool,
        capture_output: bool,
        encoding: str,
        errors: str,
        timeout: float,
        cwd: Path,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


def _execute_subprocess(
    argv: Sequence[str],
    *,
    check: bool,
    shell: bool,
    capture_output: bool,
    encoding: str,
    errors: str,
    timeout: float,
    cwd: Path,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=check,
        shell=shell,
        capture_output=capture_output,
        encoding=encoding,
        errors=errors,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )


def _controlled_environment() -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, os.environ[name])
        for name in sorted(_ALLOWED_ENVIRONMENT_NAMES)
        if name in os.environ
    )


@dataclass(frozen=True, slots=True)
class MmseqsRunContext:
    """Immutable local-only execution context for one staged MMseqs2 command."""

    cache_root: Path
    staging_dir: Path
    timeout_seconds: float
    expected_outputs: tuple[Path, ...]
    completed_outputs: tuple[Path, ...]
    executor: MmseqsExecutor
    probe: MmseqsProbe
    probe_timeout_seconds: float
    stderr_limit_chars: int
    environment: tuple[tuple[str, str], ...]

    @classmethod
    def create(
        cls,
        *,
        cache_root: Path,
        timeout_seconds: float,
        expected_output_names: Sequence[str],
        completed_outputs: Sequence[Path] = (),
        executor: MmseqsExecutor = _execute_subprocess,
        probe: MmseqsProbe | None = None,
        probe_timeout_seconds: float = 10.0,
        stderr_limit_chars: int = 4096,
        environment: Mapping[str, str] | None = None,
    ) -> Self:
        """Create a collision-resistant staging child under an absolute cache root."""

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("MMseqs2 run timeout must be finite and positive")
        if not math.isfinite(probe_timeout_seconds) or probe_timeout_seconds <= 0:
            raise ValueError("MMseqs2 probe timeout must be finite and positive")
        if (
            isinstance(stderr_limit_chars, bool)
            or stderr_limit_chars <= 0
            or stderr_limit_chars > 65_536
        ):
            raise ValueError("stderr_limit_chars must be between 1 and 65536")
        if isinstance(expected_output_names, (str, bytes)):
            raise ValueError("expected output names must be a sequence of path strings")
        output_names = tuple(expected_output_names)
        if not output_names:
            raise ValueError("at least one expected output name is required")
        output_paths = tuple(Path(name) for name in output_names)
        if any(
            not name.strip() or path.is_absolute() or path == Path(".") or ".." in path.parts
            for name, path in zip(output_names, output_paths, strict=True)
        ):
            raise ValueError("expected output names must be safe relative paths")
        if len(set(output_paths)) != len(output_paths):
            raise ValueError("expected output names must be unique")
        if not cache_root.is_absolute():
            raise ValueError("cache_root must be an absolute config-resolved path")
        completed_output_paths = tuple(completed_outputs)
        if any(not path.is_absolute() for path in completed_output_paths):
            raise ValueError("completed output paths must be absolute and config-resolved")
        if len(set(completed_output_paths)) != len(completed_output_paths):
            raise ValueError("completed output paths must be unique")
        if environment is not None and not set(environment).issubset(_ALLOWED_ENVIRONMENT_NAMES):
            raise ValueError("environment contains a non-allow-listed variable")
        resolved_cache = cache_root.expanduser().resolve()
        resolved_cache.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="psaudit-mmseqs-", dir=resolved_cache)).resolve()
        outputs = tuple(staging_dir / path for path in output_paths)
        environment_items = (
            _controlled_environment()
            if environment is None
            else tuple(sorted(environment.items(), key=lambda item: item[0]))
        )
        return cls(
            cache_root=resolved_cache,
            staging_dir=staging_dir,
            timeout_seconds=timeout_seconds,
            expected_outputs=outputs,
            completed_outputs=completed_output_paths,
            executor=executor,
            probe=probe_mmseqs if probe is None else probe,
            probe_timeout_seconds=probe_timeout_seconds,
            stderr_limit_chars=stderr_limit_chars,
            environment=environment_items,
        )


@dataclass(frozen=True, slots=True)
class MmseqsRunResult:
    """Successful local result for a staged MMseqs2 command."""

    returncode: int
    mmseqs_version: str
    resolved_executable: Path
    sanitized_argv: tuple[str, ...]
    outputs: tuple[Path, ...]
    staging_dir: Path
    stderr_tail: str


def _cleanup_staging(staging_dir: Path) -> bool:
    try:
        staging_dir.mkdir(parents=True, exist_ok=True)
        for child in staging_dir.iterdir():
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
    except OSError:
        return False
    return True


def _sanitize_stderr(value: str | bytes | None, limit: int) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
    printable = "".join(
        character if character in "\n\r\t" or character.isprintable() else "�" for character in text
    )
    redacted = _SECRET_PATTERN.sub(
        lambda match: f"{match.group('key')}: <redacted>", printable
    ).strip()
    if len(redacted) <= limit:
        return redacted
    if limit == 1:
        return "…"
    return "…" + redacted[-(limit - 1) :]


def _sanitize_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    if not argv:
        return ()
    sanitized = list(argv)
    sanitized[0] = Path(sanitized[0]).name
    if len(sanitized) < 2:
        return tuple(sanitized)
    path_tokens = {
        "easy-cluster": ("<input_fasta>", "<output_prefix>", "<temp_dir>"),
        "easy-search": ("<query_fasta>", "<target_fasta>", "<output_tsv>", "<temp_dir>"),
    }
    tokens = path_tokens.get(sanitized[1], ())
    for index, token in enumerate(tokens, start=2):
        if index < len(sanitized):
            sanitized[index] = token
    if not tokens:
        for index in range(2, len(sanitized)):
            if Path(sanitized[index]).is_absolute():
                sanitized[index] = "<path>"
    return tuple(sanitized)


def _is_safe_staged_output(path: Path, staging_dir: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(metadata.st_mode):
        return False
    try:
        resolved_output = path.resolve(strict=True)
        resolved_stage = staging_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return resolved_output.is_relative_to(resolved_stage)


def _has_valid_staging_paths(argv: tuple[str, ...], run: MmseqsRunContext) -> bool:
    if len(argv) < 2 or not argv[0]:
        return False
    command = argv[1]
    if command == "easy-search" and len(argv) >= 6:
        output_path = Path(argv[4])
        temp_path = Path(argv[5])
        expected_output = output_path.resolve() in {path.resolve() for path in run.expected_outputs}
    elif command == "easy-cluster" and len(argv) >= 5:
        output_path = Path(argv[3])
        temp_path = Path(argv[4])
        cluster_tsv = Path(f"{output_path}_cluster.tsv").resolve()
        expected_output = cluster_tsv in {path.resolve() for path in run.expected_outputs}
    else:
        return False
    if not output_path.is_absolute() or not temp_path.is_absolute() or not expected_output:
        return False
    resolved_stage = run.staging_dir.resolve()
    resolved_output = output_path.resolve()
    resolved_temp = temp_path.resolve()
    return (
        resolved_output.is_relative_to(resolved_stage)
        and resolved_temp != resolved_stage
        and resolved_temp.is_relative_to(resolved_stage)
    )


def run_mmseqs(argv: Sequence[str], run: MmseqsRunContext) -> MmseqsRunResult:
    """Probe and execute one immutable MMseqs2 argv through an injected executor."""

    logical_argv = tuple(argv)
    if any(path.exists() for path in (*run.completed_outputs, *run.expected_outputs)):
        cleanup_succeeded = _cleanup_staging(run.staging_dir)
        raise MmseqsRunError(
            "completed or staged MMseqs2 output already exists",
            staging_dir=run.staging_dir,
            cleanup_succeeded=cleanup_succeeded,
            sanitized_argv=_sanitize_argv(logical_argv),
        )
    if not _has_valid_staging_paths(logical_argv, run):
        cleanup_succeeded = _cleanup_staging(run.staging_dir)
        raise MmseqsRunError(
            "MMseqs2 argv contains an invalid staging path or command shape",
            staging_dir=run.staging_dir,
            cleanup_succeeded=cleanup_succeeded,
            sanitized_argv=_sanitize_argv(logical_argv),
        )
    tool = run.probe(logical_argv[0], timeout_seconds=run.probe_timeout_seconds)
    executed_argv = (str(tool.executable), *logical_argv[1:])
    try:
        completed = run.executor(
            executed_argv,
            check=False,
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=run.timeout_seconds,
            cwd=run.staging_dir,
            env=dict(run.environment),
        )
    except subprocess.TimeoutExpired as error:
        stderr_tail = _sanitize_stderr(error.stderr, run.stderr_limit_chars)
        cleanup_succeeded = _cleanup_staging(run.staging_dir)
        raise MmseqsRunError(
            f"MMseqs2 command timed out after {run.timeout_seconds:g} seconds",
            timed_out=True,
            stderr_tail=stderr_tail,
            staging_dir=run.staging_dir,
            cleanup_succeeded=cleanup_succeeded,
            mmseqs_version=tool.version,
            resolved_executable=tool.executable,
            sanitized_argv=_sanitize_argv(logical_argv),
        ) from error
    except OSError as error:
        cleanup_succeeded = _cleanup_staging(run.staging_dir)
        raise MmseqsRunError(
            "MMseqs2 command could not be started",
            staging_dir=run.staging_dir,
            cleanup_succeeded=cleanup_succeeded,
            mmseqs_version=tool.version,
            resolved_executable=tool.executable,
            sanitized_argv=_sanitize_argv(logical_argv),
        ) from error
    if completed.returncode != 0:
        stderr_tail = _sanitize_stderr(completed.stderr, run.stderr_limit_chars)
        cleanup_succeeded = _cleanup_staging(run.staging_dir)
        raise MmseqsRunError(
            f"MMseqs2 command exited with status {completed.returncode}",
            returncode=completed.returncode,
            stderr_tail=stderr_tail,
            staging_dir=run.staging_dir,
            cleanup_succeeded=cleanup_succeeded,
            mmseqs_version=tool.version,
            resolved_executable=tool.executable,
            sanitized_argv=_sanitize_argv(logical_argv),
        )
    unsafe_outputs = tuple(
        path for path in run.expected_outputs if not _is_safe_staged_output(path, run.staging_dir)
    )
    if unsafe_outputs:
        cleanup_succeeded = _cleanup_staging(run.staging_dir)
        raise MmseqsRunError(
            "MMseqs2 completed without all expected staged outputs as safe regular files",
            returncode=completed.returncode,
            staging_dir=run.staging_dir,
            cleanup_succeeded=cleanup_succeeded,
            mmseqs_version=tool.version,
            resolved_executable=tool.executable,
            sanitized_argv=_sanitize_argv(logical_argv),
        )
    return MmseqsRunResult(
        returncode=completed.returncode,
        mmseqs_version=tool.version,
        resolved_executable=tool.executable,
        sanitized_argv=_sanitize_argv(logical_argv),
        outputs=run.expected_outputs,
        staging_dir=run.staging_dir,
        stderr_tail=_sanitize_stderr(completed.stderr, run.stderr_limit_chars),
    )


def probe_mmseqs(executable: str, *, timeout_seconds: float = 10.0) -> MmseqsTool:
    """Resolve ``executable`` and obtain a bounded, parseable ``mmseqs version`` result."""

    requested = executable.strip()
    if not requested:
        raise ValueError("MMseqs2 executable must not be blank")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("MMseqs2 probe timeout must be finite and positive")

    discovered = shutil.which(requested)
    if discovered is None:
        raise MmseqsProbeError(f"MMseqs2 executable not found: {requested}")
    resolved = Path(discovered).expanduser().resolve()

    try:
        completed = subprocess.run(
            (str(resolved), "version"),
            check=False,
            shell=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=dict(_controlled_environment()),
        )
    except subprocess.TimeoutExpired as error:
        raise MmseqsProbeError(
            f"MMseqs2 version probe timed out after {timeout_seconds:g} seconds",
            executable=resolved,
        ) from error
    except OSError as error:
        raise MmseqsProbeError(
            f"MMseqs2 version probe failed: {error}",
            executable=resolved,
        ) from error

    if completed.returncode != 0:
        raise MmseqsProbeError(
            f"MMseqs2 version probe exited with status {completed.returncode}",
            executable=resolved,
        )

    output = completed.stdout.strip()
    match = _VERSION_PATTERN.fullmatch(output)
    if match is None:
        raise MmseqsProbeError(
            "MMseqs2 version output is empty or malformed",
            executable=resolved,
        )

    return MmseqsTool(executable=resolved, version=match.group("version"))


__all__ = [
    "MmseqsExecutor",
    "MmseqsProbe",
    "MmseqsProbeError",
    "MmseqsRunContext",
    "MmseqsRunError",
    "MmseqsRunResult",
    "MmseqsTool",
    "probe_mmseqs",
    "run_mmseqs",
]
