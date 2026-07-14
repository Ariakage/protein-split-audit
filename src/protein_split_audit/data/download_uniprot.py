# SPDX-License-Identifier: Apache-2.0

"""Paginated, provenance-capturing UniProtKB TSV downloads."""

from __future__ import annotations

import gzip
import io
import os
import platform
import re
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from protein_split_audit import __version__
from protein_split_audit.config import DownloadConfig
from protein_split_audit.provenance import (
    DownloadManifest,
    DownloadPageProvenance,
    git_metadata,
    serialize_download_manifest,
    sha256_bytes,
    sha256_file,
)

APPROVED_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "etag",
        "last-modified",
        "x-total-results",
        "x-uniprot-release",
        "x-uniprot-release-date",
    }
)
ACCEPTED_CONTENT_TYPES = ("text/plain", "text/tab-separated-values")
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
NEXT_RELATION_PATTERN = re.compile(
    r'<(?P<url>[^<>]+)>\s*;\s*[^,]*\brel\s*=\s*["\']?next["\']?',
    re.IGNORECASE,
)
NEXT_MARKER_PATTERN = re.compile(r"\brel\s*=\s*[\"']?next[\"']?", re.IGNORECASE)


class DownloadError(RuntimeError):
    """Raised when a download cannot be validated and published safely."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Published paths and structured provenance for a completed download."""

    compressed_path: Path
    manifest_path: Path
    manifest: DownloadManifest


@dataclass(frozen=True, slots=True)
class _NormalizedPage:
    header: tuple[str, ...]
    data_lines: tuple[str, ...]
    normalized_bytes: bytes


def _user_agent() -> str:
    return f"ProteinSplitAudit/{__version__} (+https://github.com/ariakage/protein-split-audit)"


def _approved_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: response.headers[name]
        for name in sorted(APPROVED_RESPONSE_HEADERS)
        if name in response.headers
    }


def _retry_delay(
    config: DownloadConfig,
    retry_number: int,
    response: httpx.Response | None,
) -> float:
    exponential = config.retry.backoff_initial_seconds * (2 ** (retry_number - 1))
    delay = min(config.retry.backoff_max_seconds, exponential)
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            with suppress(ValueError):
                parsed_retry_after = float(retry_after)
                delay = min(
                    config.retry.backoff_max_seconds,
                    max(delay, parsed_retry_after),
                )
    return float(delay)


def _request_page(
    client: httpx.Client,
    config: DownloadConfig,
    url: str,
    params: dict[str, str | int] | None,
    sleep: Callable[[float], None],
) -> httpx.Response:
    attempts = config.retry.max_retries + 1
    last_transport_error: httpx.TransportError | None = None

    for attempt in range(1, attempts + 1):
        response: httpx.Response | None = None
        try:
            response = client.get(
                url,
                params=params,
                headers={
                    "Accept": "text/tab-separated-values, text/plain;q=0.9",
                    "User-Agent": _user_agent(),
                },
                timeout=config.source.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TransportError as error:
            last_transport_error = error

        if response is not None and response.status_code not in TRANSIENT_STATUS_CODES:
            return response
        if attempt == attempts:
            detail = (
                f"HTTP {response.status_code}"
                if response is not None
                else type(last_transport_error).__name__
            )
            raise DownloadError(
                f"transient UniProt failure {detail} after {attempts} attempts"
            ) from last_transport_error
        sleep(_retry_delay(config, attempt, response))

    raise AssertionError("retry loop exhausted without returning or raising")


def _validate_success(response: httpx.Response) -> None:
    if response.status_code == 400:
        detail = " ".join(response.text.split())[:200]
        raise DownloadError(f"UniProt rejected query (HTTP 400): {detail}")
    if response.status_code >= 400:
        detail = " ".join(response.text.split())[:200]
        raise DownloadError(f"UniProt API error HTTP {response.status_code}: {detail}")

    content_type = response.headers.get("content-type", "").lower()
    if not any(content_type.startswith(expected) for expected in ACCEPTED_CONTENT_TYPES):
        raise DownloadError(f"unexpected content type: {content_type or 'missing'}")


def _normalize_page(
    response: httpx.Response,
    config: DownloadConfig,
    page_number: int,
) -> _NormalizedPage:
    try:
        text = response.content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DownloadError("TSV response is not valid UTF-8") from error
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise DownloadError("empty TSV response")

    lines = text.splitlines()
    header = tuple(lines[0].split("\t"))
    missing = [
        required for required in config.source.required_response_headers if required not in header
    ]
    if missing:
        raise DownloadError(f"missing required TSV field: {missing[0]}")

    expected = config.source.expected_response_headers
    if header != expected:
        message = "TSV header changed between pages" if page_number > 1 else "unexpected TSV header"
        raise DownloadError(message)

    data_lines: list[str] = []
    for row_number, line in enumerate(lines[1:], start=2):
        if len(line.split("\t")) != len(header):
            raise DownloadError(
                f"malformed TSV row on page {page_number}, line {row_number}: "
                f"expected {len(header)} columns"
            )
        data_lines.append(line)

    normalized = "\n".join(("\t".join(header), *data_lines)) + "\n"
    return _NormalizedPage(
        header=header,
        data_lines=tuple(data_lines),
        normalized_bytes=normalized.encode(),
    )


def _parse_total(response: httpx.Response) -> int | None:
    value = response.headers.get("x-total-results")
    if value is None:
        return None
    try:
        total = int(value)
    except ValueError as error:
        raise DownloadError(f"invalid X-Total-Results value: {value}") from error
    if total < 0:
        raise DownloadError(f"invalid X-Total-Results value: {value}")
    return total


def _next_url(response: httpx.Response, endpoint: httpx.URL) -> str | None:
    link = response.headers.get("link")
    if link is None:
        return None

    matches = list(NEXT_RELATION_PATTERN.finditer(link))
    if not matches:
        if NEXT_MARKER_PATTERN.search(link):
            raise DownloadError("malformed rel=next Link header")
        return None
    if len(matches) != 1:
        raise DownloadError("multiple rel=next links in Link header")

    candidate = httpx.URL(matches[0].group("url"))
    if (
        not candidate.is_absolute_url
        or candidate.scheme != "https"
        or candidate.host != endpoint.host
        or (candidate.port or 443) != (endpoint.port or 443)
        or candidate.path != endpoint.path
        or bool(candidate.userinfo)
    ):
        raise DownloadError("malformed rel=next URL or unapproved pagination URL")
    return str(candidate)


def _deterministic_gzip(content: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=buffer,
        compresslevel=9,
        mtime=0,
    ) as compressed:
        compressed.write(content)
    return buffer.getvalue()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _publish_outputs(
    compressed_path: Path,
    compressed_content: bytes,
    manifest_path: Path,
    manifest_content: bytes,
) -> None:
    if compressed_path.exists():
        raise DownloadError(f"refusing to overwrite raw download: {compressed_path}")
    if manifest_path.exists():
        raise DownloadError(f"refusing to overwrite manifest: {manifest_path}")

    compressed_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[Path] = []
    raw_published = False
    try:
        with tempfile.NamedTemporaryFile(dir=compressed_path.parent, delete=False) as stream:
            stream.write(compressed_content)
            temporary_raw = Path(stream.name)
        temporary_paths.append(temporary_raw)

        with tempfile.NamedTemporaryFile(dir=manifest_path.parent, delete=False) as stream:
            stream.write(manifest_content)
            temporary_manifest = Path(stream.name)
        temporary_paths.append(temporary_manifest)

        os.replace(temporary_raw, compressed_path)
        raw_published = True
        os.replace(temporary_manifest, manifest_path)
    except OSError as error:
        if raw_published:
            compressed_path.unlink(missing_ok=True)
        raise DownloadError(f"failed to publish download artifacts: {error}") from error
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)


def download_uniprot(
    config: DownloadConfig,
    *,
    project_root: Path,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DownloadResult:
    """Download, validate, normalize, and publish paginated UniProt TSV data."""

    endpoint = httpx.URL(str(config.source.endpoint))
    first_params: dict[str, str | int] = {
        "query": config.source.query,
        "format": config.source.format,
        "fields": ",".join(config.source.requested_fields),
        "size": config.source.page_size,
    }
    owned_client = client is None
    active_client = client or httpx.Client()

    page_number = 0
    next_request_url = str(endpoint)
    params: dict[str, str | int] | None = first_params
    visited_urls: set[str] = set()
    page_hashes: set[str] = set()
    combined_lines: list[str] = []
    pages: list[DownloadPageProvenance] = []
    expected_total: int | None = None
    canonical_request_url = ""
    release: str | None = None
    release_date: str | None = None

    try:
        while True:
            response = _request_page(active_client, config, next_request_url, params, sleep)
            _validate_success(response)
            request_url = str(response.request.url)
            if request_url in visited_urls:
                raise DownloadError(f"pagination loop detected at {request_url}")
            visited_urls.add(request_url)
            if not canonical_request_url:
                canonical_request_url = request_url

            page_number += 1
            page = _normalize_page(response, config, page_number)
            page_hash = sha256_bytes(page.normalized_bytes)
            if page_hash in page_hashes:
                raise DownloadError(f"duplicate page content detected on page {page_number}")
            page_hashes.add(page_hash)

            total = _parse_total(response)
            if total is not None:
                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise DownloadError(
                        f"UniProt total count changed from {expected_total} to {total}"
                    )

            page_release = response.headers.get("x-uniprot-release")
            page_release_date = response.headers.get("x-uniprot-release-date")
            if release is not None and page_release is not None and page_release != release:
                raise DownloadError("UniProt release changed between pages")
            if (
                release_date is not None
                and page_release_date is not None
                and page_release_date != release_date
            ):
                raise DownloadError("UniProt release date changed between pages")
            release = release or page_release
            release_date = release_date or page_release_date

            if page_number == 1:
                combined_lines.append("\t".join(page.header))
            combined_lines.extend(page.data_lines)
            pages.append(
                DownloadPageProvenance(
                    page_number=page_number,
                    request_url=request_url,
                    response_headers=_approved_headers(response),
                    record_count=len(page.data_lines),
                    normalized_page_sha256=page_hash,
                )
            )

            following = _next_url(response, endpoint)
            if following is None:
                break
            if following in visited_urls:
                raise DownloadError(f"pagination loop detected at {following}")
            next_request_url = following
            params = None
    finally:
        if owned_client:
            active_client.close()

    record_count = sum(page.record_count for page in pages)
    if record_count == 0:
        raise DownloadError("empty TSV response: no records")
    if expected_total is not None and record_count != expected_total:
        raise DownloadError(
            f"total count mismatch: expected {expected_total} records, downloaded {record_count}"
        )

    normalized_content = ("\n".join(combined_lines) + "\n").encode()
    compressed_content = _deterministic_gzip(normalized_content)
    compressed_path = config.output.raw_dir / config.output.compressed_filename
    manifest_path = config.output.manifest_dir / config.output.manifest_filename
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        raise DownloadError(f"uv.lock not found at project root: {lockfile}")

    timestamp = now()
    if timestamp.tzinfo is None:
        raise DownloadError("download timestamp must be timezone-aware")
    git = git_metadata(project_root)
    manifest = DownloadManifest(
        source_database=config.source.database,
        endpoint=str(config.source.endpoint),
        query=config.source.query,
        canonical_request_url=canonical_request_url,
        requested_fields=config.source.requested_fields,
        downloaded_at_utc=timestamp.astimezone(UTC),
        uniprot_release=release,
        uniprot_release_date=release_date,
        page_count=len(pages),
        record_count=record_count,
        expected_total_count=expected_total,
        normalized_content_sha256=sha256_bytes(normalized_content),
        local_compressed_file=_relative_path(compressed_path, project_root),
        local_compressed_file_sha256=sha256_bytes(compressed_content),
        software_version=__version__,
        git_commit=git.commit,
        git_dirty=git.dirty,
        python_version=platform.python_version(),
        uv_lock_sha256=sha256_file(lockfile),
        pages=tuple(pages),
    )
    _publish_outputs(
        compressed_path,
        compressed_content,
        manifest_path,
        serialize_download_manifest(manifest),
    )
    return DownloadResult(
        compressed_path=compressed_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )
