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


def test_verified_facts_section_renders_before_overview() -> None:
    report = {
        **REPORT,
        "digest_facts": {
            "metadata": {"stars": 71123, "forks": 10, "open_issues_count": 0},
            "languages": [],
            "git": {
                "last_commit_at": None,
                "commits_last_30d": 3,
                "commits_30d_capped": False,
                "open_issues": 0,
                "open_pulls": 0,
                "top_contributors": [],
            },
            "files": {
                "total_files": 11,
                "total_bytes": 1000,
                "files_by_extension": {},
                "largest_files": [],
                "line_counts": {},
            },
        },
    }
    md = render_markdown(report)
    assert "## Verified Facts (pipeline-computed)" in md
    # ground truth lands before the claim sections
    assert md.index("## Verified Facts (pipeline-computed)") < md.index("## Overview")
    assert "71,123 stars" in md


def test_no_verified_facts_section_without_annex() -> None:
    md = render_markdown(REPORT)
    assert "Verified Facts" not in md


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


# ---------------------------------------------------------------------------
# Language localization (report["language"], set from REPORT_LANGUAGE)
# ---------------------------------------------------------------------------


def test_zh_render_uses_chinese_labels() -> None:
    md = render_markdown({**REPORT, "language": "zh"})
    assert "# 仓库分析报告: pallets/flask" in md
    for heading in (
        "## 概述", "## 技术栈", "## 仓库结构", "## 架构", "## 核心模块",
        "## 入口点", "## 执行流程", "## 关键文件", "## 依赖", "## 风险",
        "## 建议阅读顺序", "## 贡献机会", "## 未知项", "## 证据摘要",
    ):
        assert heading in md
    assert "**摘要：**" in md
    assert "| 类别 | 技术 | 作用 |" in md
    assert "引用总数：" in md
    assert "5/6 条引用已验证" in md
    assert "**1 条未验证**" in md
    assert "> 注意：本报告基于降级事实" in md


def test_zh_verified_facts_keeps_english_anchor() -> None:
    report = {
        **REPORT,
        "language": "zh",
        "digest_facts": {
            "metadata": {"stars": 71123, "forks": 10, "open_issues_count": 0},
            "languages": [],
            "git": {
                "last_commit_at": None,
                "commits_last_30d": 3,
                "commits_30d_capped": False,
                "open_issues": 0,
                "open_pulls": 0,
                "top_contributors": [],
            },
            "files": {
                "total_files": 11,
                "total_bytes": 1000,
                "files_by_extension": {},
                "largest_files": [],
                "line_counts": {},
            },
        },
    }
    md = render_markdown(report)
    assert "## 已验证事实 (Verified Facts, pipeline-computed)" in md
    assert md.index("## 已验证事实 (Verified Facts, pipeline-computed)") < md.index("## 概述")
    assert "71,123 星标" in md


def test_zh_evidence_paths_never_translated() -> None:
    md = render_markdown({**REPORT, "language": "zh"})
    assert "`src/flask/app.py`" in md
    assert "`does/not/exist.py`" in md
    assert "证据：" in md


def test_en_output_byte_identical_with_language_key() -> None:
    assert render_markdown({**REPORT, "language": "en"}) == render_markdown(REPORT)


def test_unknown_language_falls_back_to_en() -> None:
    assert render_markdown({**REPORT, "language": "fr"}) == render_markdown(REPORT)
