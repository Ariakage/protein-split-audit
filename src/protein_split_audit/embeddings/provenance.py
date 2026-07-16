# SPDX-License-Identifier: Apache-2.0

"""Sanitized model snapshot manifest persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path

from protein_split_audit.embeddings.schemas import ModelSnapshotManifest
from protein_split_audit.provenance import serialize_json_model


def snapshot_manifest_path(project_root: Path, model_id: str) -> Path:
    """Return the tracked manifest path for an approved model ID."""

    return project_root / "data/manifests/models" / f"{model_id.replace('_', '-')}.snapshot.json"


def write_snapshot_manifest(path: Path, manifest: ModelSnapshotManifest) -> Path:
    """Write a new manifest atomically without overwriting an identity."""

    if path.exists():
        raise FileExistsError(f"snapshot manifest already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise FileExistsError(f"snapshot manifest staging file already exists: {temporary.name}")
    try:
        temporary.write_bytes(serialize_json_model(manifest))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_snapshot_manifest(path: Path) -> ModelSnapshotManifest:
    """Load one strict model snapshot manifest."""

    try:
        payload = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid snapshot manifest: {path.name}") from error
    return ModelSnapshotManifest.model_validate(payload)


__all__ = ["load_snapshot_manifest", "snapshot_manifest_path", "write_snapshot_manifest"]
