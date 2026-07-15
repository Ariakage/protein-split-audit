# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import fcntl
import os
import traceback
from pathlib import Path

import pytest


def test_publish_bundle_documents_advisory_lock_bypass_risk() -> None:
    from protein_split_audit.publication import publish_bundle

    documentation = publish_bundle.__doc__ or ""
    assert "advisory" in documentation.lower()
    assert "bypass" in documentation.lower()


def test_publish_bundle_preserves_caller_order_and_exact_bytes(tmp_path: Path) -> None:
    from protein_split_audit.publication import publish_bundle

    first = tmp_path / "z-parent" / "first.bin"
    second = tmp_path / "a-parent" / "second.bin"
    outputs = {first: b"first\n", second: b"second\x00payload\n"}

    published = publish_bundle(outputs)

    assert published == (first.resolve(), second.resolve())
    assert first.read_bytes() == outputs[first]
    assert second.read_bytes() == outputs[second]


def test_publish_bundle_rejects_empty_bundle(tmp_path: Path) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    with pytest.raises(PublicationError, match="empty"):
        publish_bundle({})

    assert list(tmp_path.iterdir()) == []


def test_publish_bundle_rejects_duplicate_resolved_destinations(tmp_path: Path) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    destination = tmp_path / "bundle" / "artifact.bin"
    alias = tmp_path / "bundle" / "nested" / ".." / "artifact.bin"

    with pytest.raises(PublicationError, match="duplicate"):
        publish_bundle({destination: b"first", alias: b"second"})

    assert not (tmp_path / "bundle").exists()


def test_publish_bundle_sanitizes_destination_resolution_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    private_parent = tmp_path / "private-resolution-parent"
    destination = private_parent / "artifact.bin"
    real_resolve = Path.resolve

    def failing_resolve(path: Path, *, strict: bool = False) -> Path:
        if path == private_parent:
            raise OSError(f"cannot resolve {path}")
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", failing_resolve)

    with pytest.raises(PublicationError) as raised:
        publish_bundle({destination: b"content"})

    rendered_error = "".join(traceback.format_exception(raised.value))
    assert str(tmp_path) not in rendered_error
    assert private_parent.name not in rendered_error


def test_publish_bundle_sanitizes_parent_symlink_loop_errors(tmp_path: Path) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    private_parent = tmp_path / "private-parent-symlink-loop"
    private_parent.symlink_to(private_parent)
    destination = private_parent / "artifact.bin"

    with pytest.raises(PublicationError) as raised:
        publish_bundle({destination: b"content"})

    rendered_error = "".join(traceback.format_exception(raised.value))
    assert str(tmp_path) not in rendered_error
    assert private_parent.name not in rendered_error


def test_publish_bundle_refuses_existing_destination_without_overwrite(
    tmp_path: Path,
) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    destination = tmp_path / "private-existing-name.bin"
    destination.write_bytes(b"competitor")

    with pytest.raises(PublicationError) as raised:
        publish_bundle({destination: b"ours"})

    assert destination.read_bytes() == b"competitor"
    assert str(tmp_path) not in str(raised.value)
    assert destination.name not in str(raised.value)


def test_publish_bundle_refuses_dangling_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    missing_target = tmp_path / "private-missing-target.bin"
    destination = tmp_path / "private-dangling-link.bin"
    destination.symlink_to(missing_target)

    with pytest.raises(PublicationError) as raised:
        publish_bundle({destination: b"ours"})

    assert destination.is_symlink()
    assert destination.readlink() == missing_target
    assert not missing_target.exists()
    assert str(tmp_path) not in str(raised.value)
    assert destination.name not in str(raised.value)


def test_publish_bundle_acquires_parent_locks_in_sorted_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    first_parent = tmp_path / "z-parent"
    second_parent = tmp_path / "a-parent"
    outputs = {
        first_parent / "first.bin": b"first",
        second_parent / "second.bin": b"second",
    }
    acquired: list[tuple[int, int]] = []
    real_flock = fcntl.flock

    def recording_flock(file_descriptor: int, operation: int) -> None:
        if operation & fcntl.LOCK_EX:
            status = os.fstat(file_descriptor)
            acquired.append((status.st_dev, status.st_ino))
        real_flock(file_descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", recording_flock)

    assert publication.publish_bundle(outputs) == tuple(
        destination.resolve() for destination in outputs
    )

    lock_paths = [
        parent / ".psaudit-publication.lock"
        for parent in sorted((first_parent, second_parent), key=os.fspath)
    ]
    assert acquired == [
        (lock_path.stat().st_dev, lock_path.stat().st_ino) for lock_path in lock_paths
    ]


def test_publish_bundle_rejects_cooperating_concurrent_publisher(
    tmp_path: Path,
) -> None:
    from protein_split_audit.publication import PublicationError, publish_bundle

    parent = tmp_path / "bundle"
    parent.mkdir()
    destination = parent / "artifact.bin"
    lock_path = parent / ".psaudit-publication.lock"

    with lock_path.open("a+b") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(PublicationError, match="already in progress"):
                publish_bundle({destination: b"content"})
        finally:
            fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)

    assert not destination.exists()


def test_publish_bundle_stages_all_content_and_links_in_caller_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    parent = tmp_path / "bundle"
    first = parent / "z-first.bin"
    second = parent / "a-second.bin"
    outputs = {first: b"first-content", second: b"second-content"}
    linked: list[Path] = []
    stage_sources: list[Path] = []
    real_link = os.link

    def inspecting_link(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        linked.append(destination_path)
        stage_sources.append(source_path)
        assert source_path.parent.parent == destination_path.parent
        assert source_path.parent.name.startswith(".psaudit-publication-stage-")
        assert source_path.read_bytes() == outputs[destination_path]
        if len(linked) == 1:
            assert len(tuple(source_path.parent.iterdir())) == len(outputs)
        real_link(source_path, destination_path)

    monkeypatch.setattr(publication.os, "link", inspecting_link)

    publication.publish_bundle(outputs)

    assert linked == list(outputs)
    assert len(set(stage_sources)) == len(outputs)
    assert not tuple(parent.glob(".psaudit-publication-stage-*"))


def test_publish_bundle_race_eexist_does_not_overwrite_competitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    destination = tmp_path / "private-race-destination.bin"
    competitor = b"competitor-content"
    real_link = os.link

    def racing_link(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        Path(target).write_bytes(competitor)
        real_link(source, target)

    monkeypatch.setattr(publication.os, "link", racing_link)

    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_bundle({destination: b"ours"})

    assert destination.read_bytes() == competitor
    assert not tuple(tmp_path.glob(".psaudit-publication-stage-*"))
    assert str(tmp_path) not in str(raised.value)
    assert destination.name not in str(raised.value)


@pytest.mark.parametrize(
    "failure_type",
    [KeyboardInterrupt, RuntimeError],
    ids=["keyboard-interrupt", "non-os-error"],
)
def test_publish_bundle_rolls_back_when_link_succeeds_before_non_os_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    from protein_split_audit import publication

    destination = tmp_path / "artifact.bin"
    real_link = os.link

    def link_then_fail(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        real_link(source, target)
        raise failure_type("injected failure after successful link")

    monkeypatch.setattr(publication.os, "link", link_then_fail)

    with pytest.raises(failure_type):
        publication.publish_bundle({destination: b"content"})

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".psaudit-publication-stage-*"))


def test_publish_bundle_rolls_back_partial_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    first = tmp_path / "first.bin"
    second = tmp_path / "private-second.bin"
    outputs = {first: b"first", second: b"second"}
    real_link = os.link
    calls = 0

    def failing_second_link(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(f"injected failure for {destination}")
        real_link(source, destination)

    monkeypatch.setattr(publication.os, "link", failing_second_link)

    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_bundle(outputs)

    assert not first.exists()
    assert not second.exists()
    assert not tuple(tmp_path.glob(".psaudit-publication-stage-*"))
    assert str(tmp_path) not in str(raised.value)
    assert second.name not in str(raised.value)
    rendered_error = "".join(traceback.format_exception(raised.value))
    assert str(tmp_path) not in rendered_error
    assert second.name not in rendered_error


def test_publish_bundle_rollback_removes_only_its_own_inodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    first = tmp_path / "first.bin"
    replaced = tmp_path / "replaced.bin"
    raced = tmp_path / "raced.bin"
    replacement_source = tmp_path / "replacement-source.bin"
    racer_source = tmp_path / "racer-source.bin"
    replacement_source.write_bytes(b"replacement")
    racer_source.write_bytes(b"racer")
    real_link = os.link
    calls = 0

    def competing_link(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        nonlocal calls
        calls += 1
        destination_path = Path(destination)
        if calls == 1:
            real_link(source, destination_path)
            return
        if calls == 2:
            real_link(source, destination_path)
            destination_path.unlink()
            replacement_source.replace(destination_path)
            return
        racer_source.replace(destination_path)
        real_link(source, destination_path)

    monkeypatch.setattr(publication.os, "link", competing_link)

    with pytest.raises(publication.PublicationError):
        publication.publish_bundle({first: b"first", replaced: b"ours", raced: b"ours"})

    assert not first.exists()
    assert replaced.read_bytes() == b"replacement"
    assert raced.read_bytes() == b"racer"
    assert not tuple(tmp_path.glob(".psaudit-publication-stage-*"))


def test_publish_bundle_holds_lock_through_rollback_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    parent = tmp_path / "bundle"
    first = parent / "first.bin"
    second = parent / "second.bin"
    lock_path = parent / ".psaudit-publication.lock"
    events: list[str] = []
    real_write_bytes = Path.write_bytes
    real_lstat = Path.lstat
    real_link = os.link
    real_rollback = publication._rollback_publications
    real_rmtree = publication.shutil.rmtree
    link_calls = 0
    prechecked: set[Path] = set()

    def assert_lock_is_held() -> None:
        with lock_path.open("a+b") as contender, pytest.raises(BlockingIOError):
            fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def checking_write_bytes(path: Path, content: bytes) -> int:
        if path.suffix == ".stage":
            assert_lock_is_held()
            events.append("stage")
        return real_write_bytes(path, content)

    def checking_lstat(path: Path) -> os.stat_result:
        if path in {first, second} and path not in prechecked:
            assert_lock_is_held()
            events.append("precheck")
            prechecked.add(path)
        return real_lstat(path)

    def checking_link(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        nonlocal link_calls
        assert_lock_is_held()
        events.append("link")
        link_calls += 1
        if link_calls == 2:
            raise OSError("injected publish failure")
        real_link(source, destination)

    def checking_rollback(publications: list[tuple[Path, int, int]]) -> None:
        assert_lock_is_held()
        events.append("rollback")
        real_rollback(publications)

    def checking_rmtree(path: os.PathLike[str], **kwargs: object) -> None:
        assert_lock_is_held()
        events.append("cleanup")
        real_rmtree(path, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", checking_write_bytes)
    monkeypatch.setattr(Path, "lstat", checking_lstat)
    monkeypatch.setattr(publication.os, "link", checking_link)
    monkeypatch.setattr(publication, "_rollback_publications", checking_rollback)
    monkeypatch.setattr(publication.shutil, "rmtree", checking_rmtree)

    with pytest.raises(publication.PublicationError):
        publication.publish_bundle({first: b"first", second: b"second"})

    assert events == [
        "precheck",
        "precheck",
        "stage",
        "stage",
        "link",
        "link",
        "rollback",
        "cleanup",
    ]


def test_publish_bundle_cleanup_failure_rolls_back_and_retries_without_path_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protein_split_audit import publication

    destination = tmp_path / "private-cleanup-destination.bin"
    real_rmtree = publication.shutil.rmtree
    cleanup_calls = 0

    def flaky_rmtree(path: os.PathLike[str], **kwargs: object) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise OSError(f"injected cleanup failure for {path}")
        real_rmtree(path, **kwargs)

    monkeypatch.setattr(publication.shutil, "rmtree", flaky_rmtree)

    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_bundle({destination: b"content"})

    assert not destination.exists()
    assert cleanup_calls == 2
    assert not tuple(tmp_path.glob(".psaudit-publication-stage-*"))
    rendered_error = "".join(traceback.format_exception(raised.value))
    assert str(tmp_path) not in rendered_error
    assert destination.name not in rendered_error
