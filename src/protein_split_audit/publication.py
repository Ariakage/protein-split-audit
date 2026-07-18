# SPDX-License-Identifier: Apache-2.0

"""Publish deterministic artifact bundles."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

_LOCK_NAME = ".psaudit-publication.lock"
SANITIZED_TEST_FILENAMES = frozenset(
    {
        "README.md",
        "confidence_intervals.csv",
        "confusion_matrices.csv",
        "environment_summary.json",
        "generalization_gap.csv",
        "input_hashes.json",
        "method_comparisons.csv",
        "nearest_homolog_summary.csv",
        "protocol_attestation.yaml",
        "replay_report.json",
        "test_per_class.csv",
        "test_summary.csv",
    }
)
_PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)")
_ACCESSION_VALUE = re.compile(rb"\b(?:[A-NR-Z][0-9][A-Z0-9]{3}[0-9]|[A-Z][0-9]{4})\b")
_SEQUENCE_RUN = re.compile(rb"[ACDEFGHIKLMNPQRSTVWY]{50,}")
_SECRET_VALUE = re.compile(rb"(?:ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]+)")
_FORBIDDEN_STRUCTURED_KEYS = frozenset(
    {
        "accession",
        "accessions",
        "authorization",
        "cookie",
        "correct",
        "host_path",
        "hostname",
        "password",
        "private_path",
        "query_accession",
        "sequence",
        "sequences",
        "target_accession",
        "token",
        "true_label_by_accession",
    }
)


class PublicationError(RuntimeError):
    """Raised when an artifact bundle cannot be published safely."""


def _structured_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        keys = tuple(str(key) for key in value)
        return keys + tuple(nested for item in value.values() for nested in _structured_keys(item))
    if isinstance(value, list):
        return tuple(nested for item in value for nested in _structured_keys(item))
    return ()


def validate_sanitized_test_bundle(outputs: Mapping[Path, bytes]) -> None:
    """Reject unsafe or unexpected content from a proposed public Test aggregate."""

    names = {path.name for path in outputs}
    if names != SANITIZED_TEST_FILENAMES or len(outputs) != len(SANITIZED_TEST_FILENAMES):
        raise PublicationError("Sanitized Test aggregate has an unexpected public file set.")
    for path, content in outputs.items():
        if path.suffix not in {".md", ".csv", ".json", ".yaml"}:
            raise PublicationError("Sanitized Test aggregate contains an unapproved extension.")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise PublicationError(
                "Sanitized Test aggregate must contain UTF-8 text only."
            ) from None
        if (
            _PRIVATE_PATH.search(text)
            or _ACCESSION_VALUE.search(content)
            or _SEQUENCE_RUN.search(content)
            or _SECRET_VALUE.search(content)
            or "SYNTHETIC_SECRET_CANARY" in text
        ):
            raise PublicationError("Sanitized Test aggregate failed the privacy scan.")
        if path.suffix == ".json":
            try:
                value = json.loads(content)
            except json.JSONDecodeError:
                raise PublicationError("Sanitized Test aggregate contains invalid JSON.") from None
            keys = {key.casefold() for key in _structured_keys(value)}
            if keys.intersection(_FORBIDDEN_STRUCTURED_KEYS):
                raise PublicationError("Sanitized Test aggregate contains a forbidden field.")
        if path.suffix == ".csv":
            header = text.splitlines()[0].split(",") if text.splitlines() else []
            forbidden = {field.casefold() for field in header}.intersection(
                _FORBIDDEN_STRUCTURED_KEYS
            )
            if path.name == "confusion_matrices.csv":
                forbidden -= {"true_label", "predicted_label"}
            if forbidden:
                raise PublicationError("Sanitized Test aggregate contains a forbidden column.")


def _resolve_destination(destination: Path) -> Path:
    expanded = destination.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded.parent.resolve() / expanded.name


def _acquire_locks(parents: tuple[Path, ...]) -> list[BinaryIO]:
    locks: list[BinaryIO] = []
    try:
        for parent in parents:
            try:
                lock = (parent / _LOCK_NAME).open("a+b")
            except OSError:
                raise PublicationError("Could not open an artifact publication lock.") from None
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                raise PublicationError("Artifact publication is already in progress.") from None
            except OSError:
                lock.close()
                raise PublicationError("Could not acquire an artifact publication lock.") from None
            locks.append(lock)
    except PublicationError:
        for acquired_lock in reversed(locks):
            acquired_lock.close()
        raise
    return locks


def _rollback_publications(publications: list[tuple[Path, int, int]]) -> None:
    for destination, expected_device, expected_inode in reversed(publications):
        try:
            status = destination.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        if (status.st_dev, status.st_ino) != (expected_device, expected_inode):
            continue
        try:
            destination.unlink()
        except OSError:
            continue


def _cleanup_stage_directories(stage_directories: list[Path]) -> bool:
    cleaned = True
    for stage_directory in reversed(stage_directories):
        try:
            shutil.rmtree(stage_directory)
        except FileNotFoundError:
            continue
        except OSError:
            cleaned = False
    return cleaned


def publish_bundle(outputs: Mapping[Path, bytes]) -> tuple[Path, ...]:
    """Publish a no-clobber bundle and return destinations in caller order.

    The per-directory locks are advisory. External writers that bypass those locks
    can still race publication or inode-checked rollback and are an explicit risk.
    """
    try:
        items = tuple(
            (_resolve_destination(destination), bytes(content))
            for destination, content in outputs.items()
        )
    except (OSError, RuntimeError):
        raise PublicationError("Could not resolve artifact destinations.") from None
    if not items:
        raise PublicationError("Cannot publish an empty artifact bundle.")

    destinations = tuple(destination for destination, _ in items)
    if len(set(destinations)) != len(destinations):
        raise PublicationError("Artifact bundle contains a duplicate destination.")

    parents = tuple(sorted({destination.parent for destination in destinations}))
    try:
        for parent in parents:
            parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise PublicationError("Could not prepare an artifact destination.") from None

    locks = _acquire_locks(parents)
    stage_directories: list[Path] = []
    publications: list[tuple[Path, int, int]] = []
    failure: BaseException | None = None
    try:
        try:
            for destination in destinations:
                try:
                    destination.lstat()
                except FileNotFoundError:
                    continue
                except OSError:
                    raise PublicationError("Could not inspect an artifact destination.") from None
                raise PublicationError("Refusing to overwrite an existing artifact destination.")

            stages_by_parent: dict[Path, Path] = {}
            try:
                for parent in parents:
                    stage_directory = Path(
                        tempfile.mkdtemp(prefix=".psaudit-publication-stage-", dir=parent)
                    )
                    stage_directories.append(stage_directory)
                    stages_by_parent[parent] = stage_directory

                staged_outputs: list[tuple[Path, Path]] = []
                for index, (destination, content) in enumerate(items):
                    stage = stages_by_parent[destination.parent] / f"{index:08d}.stage"
                    stage.write_bytes(content)
                    staged_outputs.append((stage, destination))
            except OSError:
                raise PublicationError("Could not stage an artifact bundle.") from None

            for stage, destination in staged_outputs:
                status = stage.lstat()
                publications.append((destination, status.st_dev, status.st_ino))
                try:
                    os.link(stage, destination)
                except FileExistsError:
                    raise PublicationError(
                        "Refusing to overwrite an existing artifact destination."
                    ) from None
                except OSError:
                    raise PublicationError("Could not publish an artifact bundle.") from None
        except OSError:
            raise PublicationError("Could not publish an artifact bundle.") from None
    except BaseException as error:
        failure = error
        _rollback_publications(publications)
    try:
        if not _cleanup_stage_directories(stage_directories):
            if failure is None:
                _rollback_publications(publications)
                failure = PublicationError("Could not clean a staged artifact bundle.")
            _cleanup_stage_directories(stage_directories)
    finally:
        for lock in reversed(locks):
            lock.close()

    if failure is not None:
        if isinstance(failure, PublicationError):
            raise failure from None
        if isinstance(failure, OSError):
            _rollback_publications(publications)
            raise PublicationError("Could not publish an artifact bundle.") from None
        raise failure
    return destinations
