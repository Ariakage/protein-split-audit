# SPDX-License-Identifier: Apache-2.0

"""Approved ESM-2 snapshot indexing and offline verification."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from protein_split_audit.embeddings.schemas import (
    EmbeddingConfig,
    ModelSnapshotManifest,
    SnapshotFile,
)
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes, sha256_file

APPROVED_SNAPSHOT_FILES = (
    "config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.txt",
)
TOKENIZER_FILES = (
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.txt",
)


class SnapshotDownloader(Protocol):
    """Narrow snapshot-download call used by production and mocked tests."""

    def __call__(
        self,
        *,
        repo_id: str,
        revision: str,
        allow_patterns: list[str],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class LoadedEsmModel:
    """A fully matched Masked-LM checkpoint and its feature encoder."""

    full_model: Any
    encoder: Any
    loading_info: dict[str, list[object]]


def snapshot_file_index(
    root: Path,
    *,
    repository: str,
    revision: str,
    downloaded_at_utc: datetime,
) -> tuple[SnapshotFile, ...]:
    """Hash an exact, flat, five-file canonical snapshot root."""

    if not root.is_dir():
        raise ValueError("model snapshot root is not a directory")
    entries = tuple(sorted(root.iterdir(), key=lambda path: path.name))
    actual_names = tuple(path.name for path in entries)
    if actual_names != APPROVED_SNAPSHOT_FILES:
        raise ValueError("model snapshot must contain exactly the approved five files")
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("approved snapshot entries must be regular files")
    return tuple(
        SnapshotFile(
            relative_path=path.name,
            byte_size=path.stat().st_size,
            sha256=sha256_file(path),
            repository=repository,
            revision=revision,
            downloaded_at_utc=downloaded_at_utc,
        )
        for path in entries
    )


def _content_projection(files: tuple[SnapshotFile, ...]) -> list[dict[str, object]]:
    return [
        {
            "relative_path": item.relative_path,
            "byte_size": item.byte_size,
            "sha256": item.sha256,
            "repository": item.repository,
            "revision": item.revision,
        }
        for item in files
    ]


def _file_by_name(files: tuple[SnapshotFile, ...], name: str) -> SnapshotFile:
    for item in files:
        if item.relative_path == name:
            return item
    raise ValueError(f"snapshot manifest missing file: {name}")


def build_snapshot_manifest(
    config: EmbeddingConfig,
    *,
    downloaded_at_utc: datetime,
) -> ModelSnapshotManifest:
    """Build a sanitized acquisition manifest from local snapshot bytes."""

    files = snapshot_file_index(
        config.model.snapshot_root,
        repository=config.model.repository,
        revision=config.model.revision,
        downloaded_at_utc=downloaded_at_utc,
    )
    weight_sha256 = _file_by_name(files, "model.safetensors").sha256
    if weight_sha256 != config.model.expected_weight_sha256:
        raise ValueError("local model.safetensors SHA-256 does not match approved weight SHA-256")
    tokenizer_projection = [
        item for item in _content_projection(files) if item["relative_path"] in TOKENIZER_FILES
    ]
    snapshot_projection: dict[str, object] = {
        "repository": config.model.repository,
        "revision": config.model.revision,
        "files": _content_projection(files),
    }
    return ModelSnapshotManifest(
        model_id=config.model_id,
        repository=config.model.repository,
        revision=config.model.revision,
        config_sha256=_file_by_name(files, "config.json").sha256,
        tokenizer_sha256=sha256_bytes(serialize_canonical_json({"files": tokenizer_projection})),
        model_weight_sha256=weight_sha256,
        snapshot_sha256=sha256_bytes(serialize_canonical_json(snapshot_projection)),
        files=files,
    )


def verify_model_snapshot(
    config: EmbeddingConfig,
    manifest: ModelSnapshotManifest,
) -> ModelSnapshotManifest:
    """Recompute every local snapshot identity without network access."""

    if not manifest.files:
        raise ValueError("snapshot manifest has no files")
    observed = build_snapshot_manifest(
        config,
        downloaded_at_utc=manifest.files[0].downloaded_at_utc,
    )
    if observed != manifest:
        raise ValueError("snapshot file index mismatch")
    return observed


def _default_snapshot_downloader(
    *,
    repo_id: str,
    revision: str,
    allow_patterns: list[str],
) -> str:
    """Import the only network-capable model function lazily."""

    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=repo_id,
        revision=revision,
        allow_patterns=allow_patterns,
    )


def fetch_model_snapshot(
    config: EmbeddingConfig,
    *,
    downloader: SnapshotDownloader | None = None,
    downloaded_at_utc: datetime,
) -> ModelSnapshotManifest:
    """Fetch one pinned snapshot and materialize an exact clean five-file root."""

    destination = config.model.snapshot_root
    if destination.exists():
        raise FileExistsError(f"model snapshot destination already exists: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fetch = downloader or _default_snapshot_downloader
    source = Path(
        fetch(
            repo_id=config.model.repository,
            revision=config.model.revision,
            allow_patterns=list(APPROVED_SNAPSHOT_FILES),
        )
    )
    if not source.is_dir():
        raise ValueError("downloaded snapshot source is not a directory")

    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as raw:
        staging = Path(raw) / "snapshot"
        staging.mkdir()
        for name in APPROVED_SNAPSHOT_FILES:
            source_file = source / name
            if not source_file.is_file():
                raise ValueError(f"downloaded snapshot missing approved file: {name}")
            shutil.copyfile(source_file, staging / name)
        staging.rename(destination)

    try:
        return build_snapshot_manifest(config, downloaded_at_utc=downloaded_at_utc)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def load_local_esm_model(
    snapshot_path: Path,
    *,
    device: str,
    intraop_threads: int,
    interop_threads: int,
    deterministic_algorithms: bool,
) -> LoadedEsmModel:
    """Load a local Masked-LM checkpoint and expose only its ESM encoder for features."""

    import torch
    from transformers import EsmForMaskedLM

    torch.set_num_threads(intraop_threads)
    if torch.get_num_interop_threads() != interop_threads:
        torch.set_num_interop_threads(interop_threads)
    torch.use_deterministic_algorithms(deterministic_algorithms)
    loaded = EsmForMaskedLM.from_pretrained(
        snapshot_path,
        local_files_only=True,
        use_safetensors=True,
        output_loading_info=True,
    )
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise RuntimeError("EsmForMaskedLM did not return loading information")
    full_model, raw_info = loaded
    if not isinstance(raw_info, dict):
        raise RuntimeError("EsmForMaskedLM returned invalid loading information")
    loading_info = {
        key: list(raw_info.get(key, []))
        for key in ("error_msgs", "mismatched_keys", "missing_keys", "unexpected_keys")
    }
    if any(loading_info.values()):
        raise RuntimeError("formal ESM snapshot has incomplete or unexpected model keys")
    full_model.to(device=device)
    full_model.eval()
    for parameter in full_model.parameters():
        parameter.requires_grad = False
    return LoadedEsmModel(
        full_model=full_model,
        encoder=full_model.esm,
        loading_info=loading_info,
    )


__all__ = [
    "APPROVED_SNAPSHOT_FILES",
    "build_snapshot_manifest",
    "fetch_model_snapshot",
    "load_local_esm_model",
    "snapshot_file_index",
    "verify_model_snapshot",
]
