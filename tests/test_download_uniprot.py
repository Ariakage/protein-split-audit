# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from protein_split_audit.config import DownloadConfig
from protein_split_audit.data.download_uniprot import DownloadError, download_uniprot
from protein_split_audit.provenance import sha256_bytes

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parents[1]
FIXED_TIME = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EXPECTED_HEADER = "Entry\tEntry Name\tProtein names\tOrganism\tOrganism (ID)\tEC number\tSequence"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_config(tmp_path: Path, *, max_retries: int = 2) -> DownloadConfig:
    fields = [
        ("accession", "Entry"),
        ("id", "Entry Name"),
        ("protein_name", "Protein names"),
        ("organism_name", "Organism"),
        ("organism_id", "Organism (ID)"),
        ("ec", "EC number"),
        ("sequence", "Sequence"),
    ]
    return DownloadConfig.model_validate(
        {
            "schema_version": 1,
            "run_name": "offline-pilot",
            "source": {
                "database": "UniProtKB/Swiss-Prot",
                "endpoint": "https://rest.uniprot.org/uniprotkb/search",
                "query": "reviewed:true AND taxonomy_id:83333 AND fragment:false AND ec:*",
                "fields": [
                    {"name": name, "response_header": header, "required": True}
                    for name, header in fields
                ],
                "page_size": 2,
                "timeout_seconds": 5.0,
            },
            "retry": {
                "max_retries": max_retries,
                "backoff_initial_seconds": 0.1,
                "backoff_max_seconds": 0.2,
            },
            "output": {
                "raw_dir": tmp_path / "data/raw",
                "manifest_dir": tmp_path / "data/manifests",
                "compressed_filename": "offline-pilot.tsv.gz",
                "manifest_filename": "offline-pilot.download.json",
                "overwrite": False,
            },
        }
    )


def response_headers(total: int, **extra: str) -> dict[str, str]:
    return {
        "content-type": "text/plain; format=tsv; charset=utf-8",
        "x-total-results": str(total),
        "x-uniprot-release": "synthetic-test-release",
        "x-uniprot-release-date": "2099-01-01",
        **extra,
    }


def run_download(
    config: DownloadConfig,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    sleep: Callable[[float], None] = lambda _delay: None,
):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return download_uniprot(
            config,
            project_root=PROJECT_ROOT,
            client=client,
            sleep=sleep,
            now=lambda: FIXED_TIME,
        )


def test_one_page_writes_normalized_gzip_and_manifest(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    body = fixture("uniprot_page_1.tsv").replace("\n", "\r\n")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers=response_headers(
                2,
                etag='"synthetic"',
                **{"set-cookie": "secret=must-not-be-saved", "authorization": "Bearer secret"},
            ),
        )

    result = run_download(config, handler)
    normalized = fixture("uniprot_page_1.tsv").encode()
    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    assert gzip.decompress(result.compressed_path.read_bytes()) == normalized
    assert result.manifest.record_count == 2
    assert result.manifest.page_count == 1
    assert result.manifest.normalized_content_sha256 == sha256_bytes(normalized)
    assert result.manifest.downloaded_at_utc == FIXED_TIME
    assert manifest["source_database"] == "UniProtKB/Swiss-Prot"
    assert manifest["query"] == config.source.query
    assert "query=" in manifest["canonical_request_url"]
    assert manifest["uniprot_release"] == "synthetic-test-release"
    assert manifest["git_dirty"] is not None
    assert manifest["uv_lock_sha256"]
    assert "set-cookie" not in manifest_text.lower()
    assert "authorization" not in manifest_text.lower()
    assert set(manifest["pages"][0]["response_headers"]) <= {
        "content-type",
        "etag",
        "last-modified",
        "x-total-results",
        "x-uniprot-release",
        "x-uniprot-release-date",
    }


def test_multiple_pages_have_one_header(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "page-2":
            return httpx.Response(
                200,
                text=fixture("uniprot_page_2.tsv"),
                headers=response_headers(3),
            )
        return httpx.Response(
            200,
            text=fixture("uniprot_page_1.tsv"),
            headers=response_headers(
                3,
                link='<https://rest.uniprot.org/uniprotkb/search?cursor=page-2>; rel="next"',
            ),
        )

    result = run_download(config, handler)
    normalized = gzip.decompress(result.compressed_path.read_bytes()).decode()

    assert normalized.count(EXPECTED_HEADER) == 1
    assert normalized.splitlines()[-1].startswith("P00003\t")
    assert result.manifest.page_count == 2
    assert result.manifest.record_count == 3
    assert result.manifest.expected_total_count == 3


def test_429_response_is_retried(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, text=fixture("uniprot_page_1.tsv"), headers=response_headers(2))

    run_download(config, handler, sleep=delays.append)

    assert attempts == 2
    assert delays == [0.1]


def test_transient_5xx_responses_use_bounded_backoff(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    statuses = iter([503, 502, 200])
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status != 200:
            return httpx.Response(status, text="transient")
        return httpx.Response(200, text=fixture("uniprot_page_1.tsv"), headers=response_headers(2))

    run_download(config, handler, sleep=delays.append)

    assert delays == [0.1, 0.2]


def test_retry_budget_is_bounded(tmp_path: Path) -> None:
    config = make_config(tmp_path, max_retries=1)
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="still unavailable")

    with pytest.raises(DownloadError, match="after 2 attempts"):
        run_download(config, handler)

    assert attempts == 2


def test_permanent_api_error_is_not_retried(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="Invalid query")

    with pytest.raises(DownloadError, match=r"rejected query.*HTTP 400"):
        run_download(config, handler)

    assert attempts == 1


def test_pagination_loop_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=fixture("uniprot_page_1.tsv"),
            headers=response_headers(4, link=f'<{request.url}>; rel="next"'),
        )

    with pytest.raises(DownloadError, match="pagination loop"):
        run_download(config, handler)


def test_duplicate_page_content_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        headers = response_headers(4)
        if request.url.params.get("cursor") is None:
            headers["link"] = (
                '<https://rest.uniprot.org/uniprotkb/search?cursor=duplicate>; rel="next"'
            )
        return httpx.Response(200, text=fixture("uniprot_page_1.tsv"), headers=headers)

    with pytest.raises(DownloadError, match="duplicate page content"):
        run_download(config, handler)


def test_malformed_tsv_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    body = f"{EXPECTED_HEADER}\nP00001\ttoo-few-columns\n"

    with pytest.raises(DownloadError, match="malformed TSV row"):
        run_download(
            config,
            lambda _request: httpx.Response(200, text=body, headers=response_headers(1)),
        )


def test_changed_header_order_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    changed = fixture("uniprot_page_2.tsv").replace(
        EXPECTED_HEADER,
        "Entry Name\tEntry\tProtein names\tOrganism\tOrganism (ID)\tEC number\tSequence",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor"):
            return httpx.Response(200, text=changed, headers=response_headers(3))
        return httpx.Response(
            200,
            text=fixture("uniprot_page_1.tsv"),
            headers=response_headers(
                3,
                link='<https://rest.uniprot.org/uniprotkb/search?cursor=changed>; rel="next"',
            ),
        )

    with pytest.raises(DownloadError, match="TSV header changed"):
        run_download(config, handler)


def test_empty_response_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(DownloadError, match="empty TSV response"):
        run_download(
            config,
            lambda _request: httpx.Response(200, text="", headers=response_headers(0)),
        )


def test_total_count_mismatch_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(DownloadError, match="expected 3 records, downloaded 2"):
        run_download(
            config,
            lambda _request: httpx.Response(
                200, text=fixture("uniprot_page_1.tsv"), headers=response_headers(3)
            ),
        )


def test_inconsistent_page_totals_are_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor"):
            return httpx.Response(
                200, text=fixture("uniprot_page_2.tsv"), headers=response_headers(4)
            )
        return httpx.Response(
            200,
            text=fixture("uniprot_page_1.tsv"),
            headers=response_headers(
                3,
                link='<https://rest.uniprot.org/uniprotkb/search?cursor=totals>; rel="next"',
            ),
        )

    with pytest.raises(DownloadError, match="total count changed"):
        run_download(config, handler)


def test_unexpected_content_type_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(DownloadError, match="unexpected content type"):
        run_download(
            config,
            lambda _request: httpx.Response(
                200,
                text=fixture("uniprot_page_1.tsv"),
                headers={"content-type": "application/json", "x-total-results": "2"},
            ),
        )


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    body = (
        fixture("uniprot_page_1.tsv")
        .replace("\tSequence", "")
        .replace("\tMAAAA", "")
        .replace("\tMCCCC", "")
    )

    with pytest.raises(DownloadError, match="missing required TSV field: Sequence"):
        run_download(
            config,
            lambda _request: httpx.Response(200, text=body, headers=response_headers(2)),
        )


def test_malformed_next_link_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(DownloadError, match="malformed rel=next"):
        run_download(
            config,
            lambda _request: httpx.Response(
                200,
                text=fixture("uniprot_page_1.tsv"),
                headers=response_headers(3, link='not-a-url; rel="next"'),
            ),
        )


def test_credential_bearing_next_link_is_rejected(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor"):
            return httpx.Response(
                200, text=fixture("uniprot_page_2.tsv"), headers=response_headers(3)
            )
        return httpx.Response(
            200,
            text=fixture("uniprot_page_1.tsv"),
            headers=response_headers(
                3,
                link=(
                    "<https://token:secret@rest.uniprot.org/uniprotkb/search?cursor=secret>; "
                    'rel="next"'
                ),
            ),
        )

    with pytest.raises(DownloadError, match="unapproved pagination URL"):
        run_download(config, handler)
