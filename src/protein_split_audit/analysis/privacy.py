# SPDX-License-Identifier: Apache-2.0

"""Small-group suppression and public release privacy checks."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ReportingStatus = Literal[
    "privacy_suppressed",
    "insufficient_sequences",
    "insufficient_components_for_ci",
    "reportable",
]

_ACCESSION = re.compile(r"\b(?:[A-Z][0-9][A-Z0-9]{3}[0-9]|[A-Z][0-9]{4})\b")
_SEQUENCE = re.compile(r"[ACDEFGHIKLMNPQRSTVWY]{50,}")
_PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)")
_SECRET = re.compile(
    r"(?:Authorization\s*:|Cookie\s*:|Bearer\s+[A-Za-z0-9._-]+|"
    r"ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})",
    re.IGNORECASE,
)
_ROW_HASH = re.compile(r"\b[0-9a-f]{64}\b")
_FORBIDDEN_FIELDS = {
    "accession",
    "query_accession",
    "nearest_train_accession",
    "sequence",
    "sequence_sha256",
    "true_label_per_record",
    "predicted_label_per_record",
}


class AnalysisPrivacyError(RuntimeError):
    """Raised when a proposed v0.6 aggregate is unsafe or structurally invalid."""


@dataclass(frozen=True, slots=True)
class GroupEligibility:
    """Frozen threshold result and safe public count rendering."""

    sequence_count: int
    component_count: int
    sequence_count_display: str
    component_count_display: str
    public_sequence_count: int | None
    public_component_count: int | None
    reporting_status: ReportingStatus

    @property
    def point_metric_allowed(self) -> bool:
        return self.reporting_status in {"insufficient_components_for_ci", "reportable"}

    @property
    def interval_allowed(self) -> bool:
        return self.reporting_status == "reportable"


def group_eligibility(sequence_count: int, component_count: int) -> GroupEligibility:
    """Apply privacy, metric, and interval thresholds in frozen precedence."""

    if (
        isinstance(sequence_count, bool)
        or isinstance(component_count, bool)
        or sequence_count < 0
        or component_count < 0
        or component_count > sequence_count
    ):
        raise ValueError("sequence and component counts are invalid")
    sequence_private = sequence_count < 5
    component_private = component_count < 3
    if sequence_private or component_private:
        status: ReportingStatus = "privacy_suppressed"
    elif sequence_count < 20:
        status = "insufficient_sequences"
    elif component_count < 10:
        status = "insufficient_components_for_ci"
    else:
        status = "reportable"
    return GroupEligibility(
        sequence_count=sequence_count,
        component_count=component_count,
        sequence_count_display="<5" if sequence_private else str(sequence_count),
        component_count_display="<3" if component_private else str(component_count),
        public_sequence_count=None if status == "privacy_suppressed" else sequence_count,
        public_component_count=None if status == "privacy_suppressed" else component_count,
        reporting_status=status,
    )


def _json_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(key) for key in value) + tuple(
            nested for item in value.values() for nested in _json_keys(item)
        )
    if isinstance(value, list):
        return tuple(nested for item in value for nested in _json_keys(item))
    return ()


def _scan_text(text: str, *, allow_artifact_hashes: bool) -> None:
    if (
        _ACCESSION.search(text)
        or _SEQUENCE.search(text)
        or _PRIVATE_PATH.search(text)
        or _SECRET.search(text)
        or (not allow_artifact_hashes and _ROW_HASH.search(text))
    ):
        raise AnalysisPrivacyError("v0.6 aggregate failed the privacy scan")


def _validate_csv(path: Path, expected: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    if "\r" in text or not text.endswith("\n"):
        raise AnalysisPrivacyError("v0.6 CSV normalization is invalid")
    _scan_text(text, allow_artifact_hashes=False)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != expected:
        raise AnalysisPrivacyError("v0.6 aggregate CSV schema is invalid")
    if {field.casefold() for field in expected}.intersection(_FORBIDDEN_FIELDS):
        raise AnalysisPrivacyError("v0.6 aggregate contains a forbidden private column")
    for row in reader:
        if row.get("reporting_status") != "privacy_suppressed":
            continue
        protected = (
            "sequence_count",
            "component_count",
            "remaining_sequence_count",
            "remaining_component_count",
            "removed_sequence_count",
            "estimate",
            "ci_lower",
            "ci_upper",
            "difference",
            "difference_ci_lower",
            "difference_ci_upper",
            "class_precision",
            "class_recall",
            "class_f1",
            "class_f1_ci_lower",
            "class_f1_ci_upper",
            "dominant_wrong_count",
            "random_minus_cluster30_class_f1",
            "gap_ci_lower",
            "gap_ci_upper",
            "point_a",
            "point_b",
            "difference_method_a_minus_method_b",
        )
        if any(row.get(field, "NA") not in {"NA", ""} for field in protected):
            raise AnalysisPrivacyError("privacy-suppressed aggregate exposes an exact value")


def validate_v060_release_bundle(root: Path) -> None:
    """Open and validate the exact 19-file v0.6 public allowlist."""

    from protein_split_audit.analysis.aggregate import CSV_SCHEMAS
    from protein_split_audit.analysis.schemas import PUBLIC_ARTIFACTS

    base = root.resolve()
    observed = {path.relative_to(base).as_posix() for path in base.rglob("*") if path.is_file()}
    if observed != set(PUBLIC_ARTIFACTS):
        raise AnalysisPrivacyError("v0.6 release bundle differs from the exact allowlist")
    for name in PUBLIC_ARTIFACTS:
        path = base / name
        if name in CSV_SCHEMAS:
            _validate_csv(path, CSV_SCHEMAS[name])
            continue
        content = path.read_bytes()
        if name.endswith(".pdf"):
            if not content.startswith(b"%PDF"):
                raise AnalysisPrivacyError("v0.6 figure is not a PDF")
            decoded = content.decode("latin-1", errors="ignore")
            if (
                "/CreationDate" in decoded
                or "/ModDate" in decoded
                or _PRIVATE_PATH.search(decoded)
                or _SECRET.search(decoded)
            ):
                raise AnalysisPrivacyError("v0.6 PDF metadata failed the privacy scan")
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise AnalysisPrivacyError("v0.6 text aggregate must be UTF-8") from None
        _scan_text(text, allow_artifact_hashes=name.endswith(".json"))
        if name.endswith(".json"):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                raise AnalysisPrivacyError("v0.6 aggregate JSON is invalid") from None
            if {key.casefold() for key in _json_keys(value)}.intersection(_FORBIDDEN_FIELDS):
                raise AnalysisPrivacyError("v0.6 aggregate JSON contains a private field")


__all__ = [
    "AnalysisPrivacyError",
    "GroupEligibility",
    "ReportingStatus",
    "group_eligibility",
    "validate_v060_release_bundle",
]
