# SPDX-License-Identifier: Apache-2.0

"""Publish deterministic artifact bundles."""

from __future__ import annotations

import fcntl
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

_LOCK_NAME = ".psaudit-publication.lock"


class PublicationError(RuntimeError):
    """Raised when an artifact bundle cannot be published safely."""


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
