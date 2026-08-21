"""Markdown rendering: every section, evidence visibility, degradation."""

from __future__ import annotations

from repo_analyzer.report.render import render_markdown

from .test_analyze_pipeline import VALID_ANALYSIS

REPORT = {
    "schema_version": "1.0",
    "repo": {
        "owner": "pallets",
        "repo": "flask",
        "url": "https://github.com/pallets/flask",
        "branch": "main",
        "ref_sha": "abc123def456",
    },
    "model": "fake-model",
    "generated_at": "2026-08-21T00:00:00+00:00",
    "analysis": VALID_ANALYSIS,
    "evidence_summary": {
        "total_citations": 6,
        "verified": 5,
        "unverified": 1,
        "unverified_list": ["does/not/exist.py"],
    },
    "warnings": ["Directory tree extraction failed"],
}


def test_all_sections_render() -> None:
    md = render_markdown(REPORT)
    for heading in (
        "## Overview", "## Tech Stack", "## Repository Structure",
        "## Architecture", "## Core Modules", "## Entry Points",
        "## Execution Flow", "## Key Files", "## Dependencies",
        "## Risks", "## Suggested Reading Order",
        "## Contribution Opportunities", "## Unknowns",
        "## Evidence Summary",
    ):
        assert heading in md


def test_header_contains_identity() -> None:
    md = render_markdown(REPORT)
    assert "# Repository Analysis Report: pallets/flask" in md
    assert "https://github.com/pallets/flask" in md
    assert "fake-model" in md
    assert "abc123def4" in md  # ref sha, truncated to 10 chars


def test_evidence_paths_stay_visible() -> None:
    md = render_markdown(REPORT)
    assert "`src/flask/app.py`" in md
    assert "Evidence:" in md


def test_grounding_flags_unverified() -> None:
    md = render_markdown(REPORT)
    assert "5/6 citations verified" in md
    assert "**1 unverified**" in md
    assert "`does/not/exist.py`" in md


def test_warnings_surface_as_degraded_note() -> None:
    md = render_markdown(REPORT)
    assert "degraded facts" in md
    assert "Directory tree extraction failed" in md


def test_empty_sections_render_gracefully() -> None:
    report = {
        "repo": {"owner": "o", "repo": "r", "url": "https://github.com/o/r",
                 "branch": "main"},
        "model": "m",
        "schema_version": "1.0",
        "analysis": {
            "overview": {"summary": "s", "purpose": "p", "evidence": ["a.py"]},
            "tech_stack": [],
            "structure": {"summary": "x", "notable_dirs": []},
            "architecture": {"summary": "y", "layers": [], "data_flow": [], "patterns": []},
            "core_modules": [],
            "entry_points": [],
            "execution_flow": [],
            "key_files": [],
            "dependencies": {"notable": [], "concerns": []},
            "risks": [],
            "reading_order": [],
            "contribution_opportunities": [],
            "unknowns": [],
        },
        "evidence_summary": {
            "total_citations": 0, "verified": 0, "unverified": 0,
            "unverified_list": [],
        },
        "warnings": [],
    }
    md = render_markdown(report)
    assert "0/0 citations verified" in md
    assert "## Overview" in md
    assert "None." in md  # unknowns section
    # empty sections collapse to nothing instead of empty tables
    assert "| Severity |" not in md
