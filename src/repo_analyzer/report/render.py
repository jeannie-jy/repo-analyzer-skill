"""Render a validated report.json into English markdown.

Rendering is deterministic and dependency-free: same report.json always
produces the same report.md. Every evidence array renders as inline
backticked paths, so the grounding of each claim stays visible in the
final document.
"""

from __future__ import annotations

from typing import Any

REPORT_TITLE = "Repository Analysis Report"


def render_markdown(report: dict) -> str:
    """Render the full report (schema_version/repo/analysis/evidence_summary)."""
    repo = report.get("repo", {})
    analysis = report.get("analysis", {})
    evidence = report.get("evidence_summary", {})

    lines: list[str] = []
    owner_repo = f"{repo.get('owner')}/{repo.get('repo')}" if repo.get("owner") else "?"
    lines.append(f"# {REPORT_TITLE}: {owner_repo}")
    lines.append("")
    lines.append(
        f"- repo: {repo.get('url', '?')}"
        f" ({repo.get('branch', '?')}"
        + (f" @ {str(repo.get('ref_sha'))[:10]}" if repo.get("ref_sha") else "")
        + ")"
    )
    lines.append(f"- model: {report.get('model', '?')}")
    lines.append(f"- schema: v{report.get('schema_version', '?')}")
    if report.get("generated_at"):
        lines.append(f"- generated: {report['generated_at']}")
    lines.append(
        f"- grounding: {evidence.get('verified', 0)}/"
        f"{evidence.get('total_citations', 0)} citations verified"
        + (
            f" (**{evidence.get('unverified', 0)} unverified**)"
            if evidence.get("unverified")
            else ""
        )
    )
    lines.append("")

    warnings = report.get("warnings") or []
    if warnings:
        lines.append("> Note: this report is based on degraded facts — "
                     "the deterministic layer recorded warnings.")
        for warning in warnings:
            lines.append(f"> - {warning}")
        lines.append("")

    lines.extend(_render_section("Overview", _render_overview(analysis)))
    lines.extend(_render_section("Tech Stack", _render_tech_stack(analysis)))
    lines.extend(_render_section("Repository Structure", _render_structure(analysis)))
    lines.extend(_render_section("Architecture", _render_architecture(analysis)))
    lines.extend(_render_section("Core Modules", _render_core_modules(analysis)))
    lines.extend(_render_section("Entry Points", _render_entry_points(analysis)))
    lines.extend(_render_section("Execution Flow", _render_execution_flow(analysis)))
    lines.extend(_render_section("Key Files", _render_key_files(analysis)))
    lines.extend(_render_section("Dependencies", _render_dependencies(analysis)))
    lines.extend(_render_section("Risks", _render_risks(analysis)))
    lines.extend(_render_section("Suggested Reading Order", _render_reading_order(analysis)))
    lines.extend(_render_section("Contribution Opportunities", _render_contributions(analysis)))
    lines.extend(_render_section("Unknowns", _render_unknowns(analysis)))

    lines.extend(_render_section("Evidence Summary", _render_evidence_summary(evidence)))
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _render_section(title: str, body: list[str]) -> list[str]:
    if not body:
        return []
    return [f"## {title}", "", *body, ""]


def _render_overview(analysis: dict) -> list[str]:
    overview = analysis.get("overview", {})
    if not overview:
        return []
    lines = [
        f"**Summary:** {overview.get('summary', '')}",
        "",
        f"**Purpose:** {overview.get('purpose', '')}",
    ]
    lines.append(_evidence_line(overview.get("evidence")))
    return lines


def _render_tech_stack(analysis: dict) -> list[str]:
    stack = analysis.get("tech_stack", [])
    rows = ["| Category | Technology | Role |\n|---|---|---|"]
    for item in stack:
        rows.append(
            f"| {item.get('category', '')} | {item.get('name', '')} | "
            f"{item.get('role', '')} {_evidence_inline(item.get('evidence'))} |"
        )
    return rows if len(rows) > 1 else []


def _render_structure(analysis: dict) -> list[str]:
    structure = analysis.get("structure", {})
    if not structure:
        return []
    lines = [f"{structure.get('summary', '')}", ""]
    for directory in structure.get("notable_dirs", []):
        lines.append(
            f"- `{directory.get('path', '')}` — {directory.get('purpose', '')} "
            f"{_evidence_inline(directory.get('evidence'))}"
        )
    return lines


def _render_architecture(analysis: dict) -> list[str]:
    architecture = analysis.get("architecture", {})
    if not architecture:
        return []
    lines = [f"{architecture.get('summary', '')}", ""]
    layers = architecture.get("layers") or []
    if layers:
        lines.append("**Layers:** " + " → ".join(f"`{l}`" for l in layers))
        lines.append("")
    for flow in architecture.get("data_flow", []):
        lines.append(
            f"- `{flow.get('from', '')}` → `{flow.get('to', '')}` "
            f"via {flow.get('mechanism', '')} {_evidence_inline(flow.get('evidence'))}"
        )
    patterns = architecture.get("patterns") or []
    if patterns:
        lines.append("")
        lines.append("**Patterns:** " + ", ".join(patterns))
    return lines


def _render_core_modules(analysis: dict) -> list[str]:
    modules = analysis.get("core_modules", [])
    lines: list[str] = []
    for module in modules:
        lines.append(f"### {module.get('name', '')} (`{module.get('path', '')}`)")
        lines.append("")
        lines.append(f"{module.get('responsibility', '')} {_evidence_inline(module.get('evidence'))}")
        symbols = module.get("key_symbols") or []
        if symbols:
            lines.append("")
            lines.append("Key symbols:")
            for symbol in symbols:
                lines.append(
                    f"- `{symbol.get('symbol', '')}` — `{symbol.get('location', '')}`"
                )
        relationships = module.get("relationships") or []
        if relationships:
            lines.append("")
            lines.append("Relationships:")
            for rel in relationships:
                lines.append(
                    f"- with `{rel.get('with', '')}` via {rel.get('mechanism', '')} "
                    f"{_evidence_inline(rel.get('evidence'))}"
                )
        lines.append("")
    return lines


def _render_entry_points(analysis: dict) -> list[str]:
    points = analysis.get("entry_points", [])
    rows = ["| Path | Kind | Confidence | Invocation |\n|---|---|---|---|"]
    for entry in points:
        rows.append(
            f"| `{entry.get('path', '')}` | {entry.get('kind', '')} | "
            f"{entry.get('confidence', '')} | `{entry.get('invocation', '')}` |"
        )
    rows.append("")
    for entry in points:
        rows.append(
            f"- **{entry.get('path', '')}**: {entry.get('rationale', '')} "
            f"{_evidence_inline(entry.get('evidence'))}"
        )
    return rows if len(rows) > 2 else []


def _render_execution_flow(analysis: dict) -> list[str]:
    flow = analysis.get("execution_flow", [])
    lines: list[str] = []
    for step in flow:
        lines.append(
            f"{step.get('step', '')}. {step.get('description', '')} "
            f"{_evidence_inline(step.get('evidence'))}"
        )
    return lines


def _render_key_files(analysis: dict) -> list[str]:
    files = analysis.get("key_files", [])
    lines: list[str] = []
    for file in files:
        lines.append(
            f"- `{file.get('path', '')}` — {file.get('why', '')} "
            f"{_evidence_inline(file.get('evidence'))}"
        )
    return lines


def _render_dependencies(analysis: dict) -> list[str]:
    dependencies = analysis.get("dependencies", {})
    lines: list[str] = []
    notable = dependencies.get("notable") or []
    if notable:
        lines.append("**Notable dependencies:**")
        for dep in notable:
            lines.append(
                f"- {dep.get('name', '')} — {dep.get('purpose', '')} "
                f"{_evidence_inline(dep.get('evidence'))}"
            )
    concerns = dependencies.get("concerns") or []
    if concerns:
        lines.append("")
        lines.append("**Concerns:**")
        for concern in concerns:
            lines.append(
                f"- {concern.get('description', '')} "
                f"{_evidence_inline(concern.get('evidence'))}"
            )
    return lines


def _render_risks(analysis: dict) -> list[str]:
    risks = analysis.get("risks", [])
    rows = ["| Severity | Category | Risk |\n|---|---|---|"]
    for risk in risks:
        rows.append(
            f"| {risk.get('severity', '')} | {risk.get('category', '')} | "
            f"{risk.get('description', '')} {_evidence_inline(risk.get('evidence'))} |"
        )
    if risks:
        rows.append("")
        for risk in risks:
            mitigation = risk.get("mitigation")
            if mitigation:
                rows.append(
                    f"- **Mitigation ({risk.get('category', '')})**: {mitigation}"
                )
    return rows if len(rows) > 1 else []


def _render_reading_order(analysis: dict) -> list[str]:
    order = analysis.get("reading_order", [])
    lines: list[str] = []
    for step in order:
        lines.append(
            f"{step.get('step', '')}. `{step.get('target', '')}` — {step.get('why', '')}"
        )
    return lines


def _render_contributions(analysis: dict) -> list[str]:
    opportunities = analysis.get("contribution_opportunities", [])
    lines: list[str] = []
    for opportunity in opportunities:
        related = " ".join(f"`{p}`" for p in (opportunity.get("related_files") or []))
        lines.append(
            f"- **{opportunity.get('area', '')}** ({opportunity.get('difficulty', '')}): "
            f"{opportunity.get('description', '')} "
            f"{_evidence_inline(opportunity.get('evidence'))}"
            + (f" — touches {related}" if related else "")
        )
    return lines


def _render_unknowns(analysis: dict) -> list[str]:
    unknowns = analysis.get("unknowns") or []
    if not unknowns:
        return ["None."]
    return [f"- {item}" for item in unknowns]


def _render_evidence_summary(evidence: dict) -> list[str]:
    lines = [
        f"- total citations: **{evidence.get('total_citations', 0)}**",
        f"- verified against tree: **{evidence.get('verified', 0)}**",
        f"- unverified: **{evidence.get('unverified', 0)}**",
    ]
    unverified = evidence.get("unverified_list") or []
    for path in unverified:
        lines.append(f"  - `{path}`")
    return lines


def _evidence_inline(evidence: Any) -> str:
    """Render an evidence array as inline backticked paths."""
    paths = [p for p in (evidence or []) if isinstance(p, str)]
    if not paths:
        return "_no evidence_"
    return "".join(f" [`{p}`]" for p in paths)


def _evidence_line(evidence: Any) -> str:
    """Render evidence as its own line."""
    paths = [p for p in (evidence or []) if isinstance(p, str)]
    if not paths:
        return "_no evidence_"
    return "Evidence: " + " ".join(f"`{p}`" for p in paths)
