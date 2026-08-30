"""Deterministic label localization for the rendered report.

The markdown render is a pure function of (report.json, language): the
English values below are byte-identical to the pre-localization literals,
so ``language="en"`` output never changes. ``zh`` translates section
titles, field labels, and deterministic glue — never the content the LLM
wrote, never evidence paths, never numbers.

Only languages in ``SUPPORTED_LANGUAGES`` have translations; anything
else falls back to English (a typo like ``zh-cn`` silently renders en
rather than crash a report render).
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("en", "zh")

L10N: dict[str, dict[str, str]] = {
    # --- report header -----------------------------------------------------
    "title": {"en": "Repository Analysis Report", "zh": "仓库分析报告"},
    "header.repo": {"en": "repo:", "zh": "仓库："},
    "header.model": {"en": "model:", "zh": "模型："},
    "header.schema": {"en": "schema:", "zh": "schema："},
    "header.generated": {"en": "generated:", "zh": "生成时间："},
    "header.grounding": {"en": "grounding:", "zh": "证据校验："},
    "grounding.verified": {"en": "citations verified", "zh": "条引用已验证"},
    "grounding.unverified": {"en": "unverified", "zh": "条未验证"},
    "warnings.note": {
        "en": "> Note: this report is based on degraded facts — "
        "the deterministic layer recorded warnings.",
        "zh": "> 注意：本报告基于降级事实——确定性层记录了警告。",
    },
    # --- section titles (14: 13 claim sections + evidence summary) ---------
    "section.overview": {"en": "Overview", "zh": "概述"},
    "section.tech_stack": {"en": "Tech Stack", "zh": "技术栈"},
    "section.structure": {"en": "Repository Structure", "zh": "仓库结构"},
    "section.architecture": {"en": "Architecture", "zh": "架构"},
    "section.core_modules": {"en": "Core Modules", "zh": "核心模块"},
    "section.entry_points": {"en": "Entry Points", "zh": "入口点"},
    "section.execution_flow": {"en": "Execution Flow", "zh": "执行流程"},
    "section.key_files": {"en": "Key Files", "zh": "关键文件"},
    "section.dependencies": {"en": "Dependencies", "zh": "依赖"},
    "section.risks": {"en": "Risks", "zh": "风险"},
    "section.reading_order": {"en": "Suggested Reading Order", "zh": "建议阅读顺序"},
    "section.contributions": {"en": "Contribution Opportunities", "zh": "贡献机会"},
    "section.unknowns": {"en": "Unknowns", "zh": "未知项"},
    "section.evidence_summary": {"en": "Evidence Summary", "zh": "证据摘要"},
    # The English anchor stays in the zh title: the prompt contract and the
    # judge rubric both reference the section as "Verified Facts" — the
    # anchor keeps those references literally true under either language.
    "section.verified_facts": {
        "en": "Verified Facts (pipeline-computed)",
        "zh": "已验证事实 (Verified Facts, pipeline-computed)",
    },
    # --- inline labels ------------------------------------------------------
    "overview.summary": {"en": "**Summary:**", "zh": "**摘要：**"},
    "overview.purpose": {"en": "**Purpose:**", "zh": "**目的：**"},
    "evidence.prefix": {"en": "Evidence:", "zh": "证据："},
    "evidence.none": {"en": "_no evidence_", "zh": "_无证据_"},
    "core.key_symbols": {"en": "Key symbols:", "zh": "关键符号："},
    "core.relationships": {"en": "Relationships:", "zh": "关联关系："},
    "arch.layers": {"en": "**Layers:**", "zh": "**层：**"},
    "arch.patterns": {"en": "**Patterns:**", "zh": "**模式：**"},
    "deps.notable": {"en": "**Notable dependencies:**", "zh": "**显著依赖：**"},
    "deps.concerns": {"en": "**Concerns:**", "zh": "**关注点：**"},
    "risks.mitigation": {"en": "**Mitigation ({cat})**", "zh": "**缓解措施（{cat}）**"},
    "contrib.touches": {"en": "touches", "zh": "涉及"},
    "flow.via": {"en": "via", "zh": "经由"},
    "unknowns.none": {"en": "None.", "zh": "无。"},
    # --- table headers ------------------------------------------------------
    "table.tech_stack": {
        "en": "| Category | Technology | Role |\n|---|---|---|",
        "zh": "| 类别 | 技术 | 作用 |\n|---|---|---|",
    },
    "table.entry_points": {
        "en": "| Path | Kind | Confidence | Invocation |\n|---|---|---|---|",
        "zh": "| 路径 | 类型 | 置信度 | 调用方式 |\n|---|---|---|---|",
    },
    "table.risks": {
        "en": "| Severity | Category | Risk |\n|---|---|---|",
        "zh": "| 严重性 | 类别 | 风险 |\n|---|---|---|",
    },
    # --- evidence summary ---------------------------------------------------
    "evid.total": {"en": "total citations:", "zh": "引用总数："},
    "evid.verified": {"en": "verified against tree:", "zh": "对照目录树已验证："},
    "evid.unverified": {"en": "unverified:", "zh": "未验证："},
    # --- digest facts annex -------------------------------------------------
    "digest.metadata": {"en": "metadata:", "zh": "元数据："},
    "digest.languages": {"en": "languages:", "zh": "语言："},
    "digest.git": {"en": "git:", "zh": "git："},
    "digest.files": {"en": "files:", "zh": "文件："},
    "digest.files_count": {"en": "files", "zh": "个文件"},
    "digest.stars": {"en": "stars", "zh": "星标"},
    "digest.forks": {"en": "forks", "zh": "复刻"},
    "digest.open_issues_meta": {
        "en": "open issues (repo metadata, includes PRs)",
        "zh": "开放 issue（仓库元数据，含 PR）",
    },
    "digest.bytes": {"en": "bytes", "zh": "字节"},
    "digest.last_commit": {"en": "last commit", "zh": "最近提交"},
    "digest.commits_30d": {"en": "commits (30d)", "zh": "提交数（30 天）"},
    "digest.capped": {"en": "(capped)", "zh": "（封顶）"},
    # The trailing colon is part of the label so zh can use the full-width
    # 冒号; en keeps its ASCII ":" (byte-identical to pre-zh output).
    "digest.open_issues_search": {
        "en": "open issues (issues search, excludes PRs):",
        "zh": "开放 issue（issue 搜索，不含 PR）：",
    },
    "digest.open_prs": {"en": "open PRs:", "zh": "开放 PR："},
    "digest.top_contributors": {"en": "top contributors:", "zh": "主要贡献者："},
    "digest.largest": {"en": "largest:", "zh": "最大的："},
    "digest.lines": {"en": "lines", "zh": "行"},
    "digest.bytes_unit": {"en": "B", "zh": "B"},
}


def label(key: str, language: str = "en") -> str:
    """The label for ``key`` in ``language``, English when untranslated.

    Unknown keys raise ``KeyError`` so a typo surfaces at development time
    instead of silently rendering English where a translation exists.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = "en"
    return L10N[key][language]
