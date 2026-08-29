# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_contribution_guide_references_only_publicly_tracked_prerequisites() -> None:
    guide = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "AGENTS.md" not in guide
    assert "docs/PRD.md" not in guide
    for path in (
        "README.md",
        "docs/protocol.md",
        "docs/methods_paper_scope.md",
        "SECURITY.md",
        "SUPPORT.md",
        "GOVERNANCE.md",
    ):
        assert path in guide or path == "README.md"
        assert (ROOT / path).is_file()


def test_issue_templates_are_valid_and_preserve_the_data_boundary() -> None:
    template_dir = ROOT / ".github/ISSUE_TEMPLATE"
    bug = yaml.safe_load((template_dir / "bug_report.yml").read_bytes())
    reproduction = yaml.safe_load((template_dir / "independent_reproduction.yml").read_bytes())
    config = yaml.safe_load((template_dir / "config.yml").read_bytes())

    assert bug["name"] == "Bug report"
    assert reproduction["name"] == "Independent reproduction report"
    assert config["blank_issues_enabled"] is True
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(template_dir.glob("*.yml"))
    )
    assert "Do not attach protein records" in combined
    assert "private or controlled material" in combined


def test_joss_preparation_is_formatted_but_not_misrepresented_as_eligible() -> None:
    manuscript = (ROOT / "paper/paper.md").read_text(encoding="utf-8")
    venue = (ROOT / "docs/venue_assessment.md").read_text(encoding="utf-8")
    readiness = yaml.safe_load((ROOT / "paper/readiness.yaml").read_bytes())
    prose = manuscript.split("---", maxsplit=2)[-1]
    word_count = len(re.findall(r"\b[\w-]+\b", prose))

    assert 750 <= word_count <= 1750
    assert "# State of the field" in manuscript
    assert "not currently eligible for JOSS submission" in venue
    assert "after 2027-01-14" in venue
    assert readiness["submission_status"] == "blocked"
    assert readiness["blocked"]["public_development_history_over_six_months"] is False
    assert readiness["blocked"]["external_research_adoption"] is False
