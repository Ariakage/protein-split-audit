# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_manuscript_has_required_methods_paper_sections() -> None:
    manuscript = (ROOT / "paper/paper.md").read_text(encoding="utf-8")

    for heading in (
        "# Summary",
        "# Statement of need",
        "# State of the field",
        "# Software design",
        "# Bounded pilot demonstration",
        "# Reproducibility and availability",
        "# Research impact",
        "# Limitations",
        "# AI-use disclosure",
        "# Acknowledgements",
    ):
        assert heading in manuscript
    assert "not offered as a representative enzyme benchmark" in manuscript
    assert "author: Aria Chen" in manuscript
    assert re.search(
        r"All\s+21 prespecified Random-minus-cluster Macro-F1 intervals include zero",
        manuscript,
    )


def test_every_manuscript_citation_has_a_bibliography_entry() -> None:
    manuscript = (ROOT / "paper/paper.md").read_text(encoding="utf-8")
    bibliography = (ROOT / "paper/paper.bib").read_text(encoding="utf-8")
    citation_keys = {
        key for group in re.findall(r"\[@([^]]+)\]", manuscript) for key in group.split(";")
    }
    bibliography_keys = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bibliography))

    assert citation_keys
    assert citation_keys <= bibliography_keys


def test_paper_makefile_builds_html_and_pdf_without_tracking_outputs() -> None:
    makefile = (ROOT / "paper/Makefile").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "--citeproc --standalone" in makefile
    assert "--pdf-engine=$(PDF_ENGINE)" in makefile
    assert "/paper/build/" in ignore


def test_bilingual_typst_manuscript_carries_both_languages_and_frozen_metadata() -> None:
    bibliography = (ROOT / "docs/paper/references.bib").read_text(encoding="utf-8")
    bibliography_keys = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bibliography))
    required_citations = {
        "teufel2023graphpart",
        "ferrerflorensa2024spanseq",
        "joeres2025datasail",
        "steinegger2017mmseqs2",
        "uniprot2025",
        "lin2023esm2",
        "hermann2024pretraining",
        "pedregosa2011scikit",
        "proteinsplitaudit",
    }

    manuscript = (ROOT / "docs/paper/paper.typ").read_text(encoding="utf-8")
    assert "@preview/elegant-paper:0.1.0" in manuscript
    assert "Aria Chen" in manuscript
    assert "Jiajie Chen" in manuscript
    assert "陈佳杰" in manuscript
    assert "Hangzhou No.11 High School" in manuscript
    assert "杭州市第十一中学" in manuscript
    assert "ariakage233@gmail.com" in manuscript
    assert "0009-0001-6214-219X" in manuscript
    assert "../../results/released/v0.6.0/figures/macro_f1_by_split.pdf" in manuscript
    assert "../../results/released/v0.6.0/figures/generalization_gap.pdf" in manuscript
    assert "\N{EM DASH}" not in manuscript
    assert "\N{EN DASH}" not in manuscript
    assert required_citations <= set(re.findall(r"@([A-Za-z][A-Za-z0-9]+)", manuscript))

    cjk_count = sum(1 for char in manuscript if "\u4e00" <= char <= "\u9fff")
    latin_words = len(re.findall(r"[A-Za-z]{4,}", manuscript))
    assert cjk_count >= 2000
    assert latin_words >= 600
    for heading in ("Introduction", "Workflow", "Results", "Conclusion"):
        assert f"({heading})" in manuscript

    assert required_citations <= bibliography_keys
    assert "/docs/paper/build/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_public_scope_blocks_unsupported_claims() -> None:
    scope = (ROOT / "docs/methods_paper_scope.md").read_text(encoding="utf-8")

    for limitation in (
        "not a new splitting-algorithm paper",
        "not representative of bacteria",
        "does not claim that Random splitting inflated",
        "not known to be independent of its pretraining corpus",
        "synthetic demo supplies software evidence only",
    ):
        assert limitation in scope


def test_stable_citation_metadata_is_not_changed_during_development() -> None:
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

    assert "version: 0.7.0" in citation
    assert "version: 0.8.0" not in citation


def test_root_software_license_matches_canonical_license_text() -> None:
    assert (ROOT / "LICENSE").read_bytes() == (ROOT / "LICENSES/Apache-2.0.txt").read_bytes()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license-files = ["LICENSE"]' in pyproject


def test_readiness_record_does_not_fabricate_submission_completion() -> None:
    readiness = yaml.safe_load((ROOT / "paper/readiness.yaml").read_bytes())

    assert readiness["submission_status"] == "blocked"
    assert readiness["completed"]["public_synthetic_demo_present"] is True
    assert readiness["completed"]["author_affiliation_confirmed"] is True
    assert readiness["completed"]["corresponding_author_metadata_confirmed"] is True
    assert readiness["completed"]["bilingual_typst_manuscript_present"] is True
    assert readiness["blocked"]["target_journal"] == "Journal of Open Research Software (JORS)"
    assert readiness["blocked"]["correspondence_postal_address_if_required"] is None
    assert readiness["blocked"]["independent_human_reproduction"] is True
    assert readiness["blocked"]["submission_release_doi"] == "10.5281/zenodo.22164608"


def test_zenodo_metadata_template_stays_doi_free() -> None:
    # The archive DOI belongs to the deposited Zenodo record
    # (10.5281/zenodo.22164608), not to the deposit metadata template.
    metadata = (ROOT / ".zenodo.json").read_text(encoding="utf-8")

    assert '"license": "Apache-2.0"' in metadata
    assert '"doi"' not in metadata


def test_reported_pilot_numbers_match_immutable_release_aggregates() -> None:
    v020 = ROOT / "results/released/v0.2.0"
    cohort = json.loads((v020 / "pilot-v1.cohort.json").read_bytes())
    selected_counts = [
        row["selected_count"] for row in cohort["class_summaries"] if row["selected"]
    ]
    assert cohort["artifacts"]["cohort_manifest"]["row_count"] == 442
    assert selected_counts == [192, 85, 59, 57, 49]

    expected_components = {"cluster70": 437, "cluster50": 427, "cluster30": 398}
    for name, expected in expected_components.items():
        manifest = json.loads((v020 / f"pilot-v1.{name}.json").read_bytes())
        assert manifest["counts"]["strict_component_count"] == expected

    split_summary = json.loads((v020 / "split_summary.json").read_bytes())
    assert all(
        split["counts"] == {"test": 66, "train": 308, "validation": 68}
        for split in split_summary["splits"].values()
    )
    random_audit = json.loads((v020 / "random.audit.json").read_bytes())
    assert random_audit["counts"]["exceedance_counts"] == {
        "0.30": 4,
        "0.50": 2,
        "0.70": 0,
    }

    with (ROOT / "results/released/v0.5.0/generalization_gap.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        gaps = tuple(csv.DictReader(stream))
    assert len(gaps) == 21
    assert all(float(row["lower"]) <= 0 <= float(row["upper"]) for row in gaps)
