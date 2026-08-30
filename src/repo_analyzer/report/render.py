"""Render a validated report.json into markdown (English or Chinese).

Rendering is deterministic and dependency-free: same report.json always
produces the same report.md. The language comes from the report's
``language`` key (set by the pipeline from ``REPORT_LANGUAGE``; default
English), and every title/label goes through :mod:`repo_analyzer.report
.labels` — so ``en`` output is byte-identical to a report without the
key. Every evidence array renders as inline backticked paths, so the
grounding of each claim stays visible in the final document. A
``digest_facts`` top-level block (pipeline-computed) renders as the
"Verified Facts" section; reports without it render as before.
"""

from __future__ import annotations

from typing import Any

from .digest_facts import render_digest_facts, section_title
from .labels import label

REPORT_TITLE = "Repository Analysis Report"


def render_markdown(report: dict) -> str:
    """Render the full report (schema_version/repo/analysis/evidence_summary)."""
    repo = report.get("repo", {})
    analysis = report.get("analysis", {})
    evidence = report.get("evidence_summary", {})
    language = report.get("language") or "en"

    lines: list[str] = []
    owner_repo = f"{repo.get('owner')}/{repo.get('repo')}" if repo.get("owner") else "?"
    lines.append(f"# {label('title', language)}: {owner_repo}")
    lines.append("")
    lines.append(
        f"- {label('header.repo', language)} {repo.get('url', '?')}"
        f" ({repo.get('branch', '?')}"
        + (f" @ {str(repo.get('ref_sha'))[:10]}" if repo.get("ref_sha") else "")
        + ")"
    )
    lines.append(f"- {label('header.model', language)} {report.get('model', '?')}")
    lines.append(f"- {label('header.schema', language)} v{report.get('schema_version', '?')}")
    if report.get("generated_at"):
        lines.append(f"- {label('header.generated', language)} {report['generated_at']}")
    lines.append(
        f"- {label('header.grounding', language)} {evidence.get('verified', 0)}/"
        f"{evidence.get('total_citations', 0)} {label('grounding.verified', language)}"
        + (
            f" (**{evidence.get('unverified', 0)} "
            f"{label('grounding.unverified', language)}**)"
            if evidence.get("unverified")
            else ""
        )
    )
    lines.append("")

    warnings = report.get("warnings") or []
    if warnings:
        lines.append(f"{label('warnings.note', language)}")
        for warning in warnings:
            lines.append(f"> - {warning}")
        lines.append("")

    # Verified-facts annex first, so the judge (and any reader) sees the
    # pipeline-verified numbers before the claim sections that restate them.
    annex = report.get("digest_facts")
    if annex:
        lines.extend(
            _render_section(section_title(language), render_digest_facts(annex, language))
        )

    lines.extend(_render_section(label("section.overview", language), _render_overview(analysis, language)))
    lines.extend(_render_section(label("section.tech_stack", language), _render_tech_stack(analysis, language)))
    lines.extend(_render_section(label("section.structure", language), _render_structure(analysis, language)))
    lines.extend(_render_section(label("section.architecture", language), _render_architecture(analysis, language)))
    lines.extend(_render_section(label("section.core_modules", language), _render_core_modules(analysis, language)))
    lines.extend(_render_section(label("section.entry_points", language), _render_entry_points(analysis, language)))
    lines.extend(_render_section(label("section.execution_flow", language), _render_execution_flow(analysis, language)))
    lines.extend(_render_section(label("section.key_files", language), _render_key_files(analysis, language)))
    lines.extend(_render_section(label("section.dependencies", language), _render_dependencies(analysis, language)))
    lines.extend(_render_section(label("section.risks", language), _render_risks(analysis, language)))
    lines.extend(_render_section(label("section.reading_order", language), _render_reading_order(analysis, language)))
    lines.extend(_render_section(label("section.contributions", language), _render_contributions(analysis, language)))
    lines.extend(_render_section(label("section.unknowns", language), _render_unknowns(analysis, language)))

    lines.extend(_render_section(
        label("section.evidence_summary", language), _render_evidence_summary(evidence, language)
    ))
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _render_section(title: str, body: list[str]) -> list[str]:
    if not body:
        return []
    return [f"## {title}", "", *body, ""]


def _render_overview(analysis: dict, language: str = "en") -> list[str]:
    overview = analysis.get("overview", {})
    if not overview:
        return []
    lines = [
        f"{label('overview.summary', language)} {overview.get('summary', '')}",
        "",
        f"{label('overview.purpose', language)} {overview.get('purpose', '')}",
    ]
    lines.append(_evidence_line(overview.get("evidence"), language))
    return lines


def _render_tech_stack(analysis: dict, language: str = "en") -> list[str]:
    stack = analysis.get("tech_stack", [])
    rows = [label("table.tech_stack", language)]
    for item in stack:
        rows.append(
            f"| {item.get('category', '')} | {item.get('name', '')} | "
            f"{item.get('role', '')} {_evidence_inline(item.get('evidence'), language)} |"
        )
    return rows if len(rows) > 1 else []


def _render_structure(analysis: dict, language: str = "en") -> list[str]:
    structure = analysis.get("structure", {})
    if not structure:
        return []
    lines = [f"{structure.get('summary', '')}", ""]
    for directory in structure.get("notable_dirs", []):
        lines.append(
            f"- `{directory.get('path', '')}` — {directory.get('purpose', '')} "
            f"{_evidence_inline(directory.get('evidence'), language)}"
        )
    return lines


def _render_architecture(analysis: dict, language: str = "en") -> list[str]:
    architecture = analysis.get("architecture", {})
    if not architecture:
        return []
    lines = [f"{architecture.get('summary', '')}", ""]
    layers = architecture.get("layers") or []
    if layers:
        lines.append(f"{label('arch.layers', language)} " + " → ".join(f"`{l}`" for l in layers))
        lines.append("")
    for flow in architecture.get("data_flow", []):
        lines.append(
            f"- `{flow.get('from', '')}` → `{flow.get('to', '')}` "
            f"{label('flow.via', language)} {flow.get('mechanism', '')} "
            f"{_evidence_inline(flow.get('evidence'), language)}"
        )
    patterns = architecture.get("patterns") or []
    if patterns:
        lines.append("")
        lines.append(f"{label('arch.patterns', language)} " + ", ".join(patterns))
    return lines


def _render_core_modules(analysis: dict, language: str = "en") -> list[str]:
    modules = analysis.get("core_modules", [])
    lines: list[str] = []
    for module in modules:
        lines.append(f"### {module.get('name', '')} (`{module.get('path', '')}`)")
        lines.append("")
        lines.append(f"{module.get('responsibility', '')} {_evidence_inline(module.get('evidence'), language)}")
        symbols = module.get("key_symbols") or []
        if symbols:
            lines.append("")
            lines.append(label("core.key_symbols", language))
            for symbol in symbols:
                lines.append(
                    f"- `{symbol.get('symbol', '')}` — `{symbol.get('location', '')}`"
                )
        relationships = module.get("relationships") or []
        if relationships:
            lines.append("")
            lines.append(label("core.relationships", language))
            for rel in relationships:
                lines.append(
                    f"- with `{rel.get('with', '')}` "
                    f"{label('flow.via', language)} {rel.get('mechanism', '')} "
                    f"{_evidence_inline(rel.get('evidence'), language)}"
                )
        lines.append("")
    return lines


def _render_entry_points(analysis: dict, language: str = "en") -> list[str]:
    points = analysis.get("entry_points", [])
    rows = [label("table.entry_points", language)]
    for entry in points:
        rows.append(
            f"| `{entry.get('path', '')}` | {entry.get('kind', '')} | "
            f"{entry.get('confidence', '')} | `{entry.get('invocation', '')}` |"
        )
    rows.append("")
    for entry in points:
        rows.append(
            f"- **{entry.get('path', '')}**: {entry.get('rationale', '')} "
            f"{_evidence_inline(entry.get('evidence'), language)}"
        )
    return rows if len(rows) > 2 else []


def _render_execution_flow(analysis: dict, language: str = "en") -> list[str]:
    flow = analysis.get("execution_flow", [])
    lines: list[str] = []
    for step in flow:
        lines.append(
            f"{step.get('step', '')}. {step.get('description', '')} "
            f"{_evidence_inline(step.get('evidence'), language)}"
        )
    return lines


def _render_key_files(analysis: dict, language: str = "en") -> list[str]:
    files = analysis.get("key_files", [])
    lines: list[str] = []
    for file in files:
        lines.append(
            f"- `{file.get('path', '')}` — {file.get('why', '')} "
            f"{_evidence_inline(file.get('evidence'), language)}"
        )
    return lines


def _render_dependencies(analysis: dict, language: str = "en") -> list[str]:
    dependencies = analysis.get("dependencies", {})
    lines: list[str] = []
    notable = dependencies.get("notable") or []
    if notable:
        lines.append(label("deps.notable", language))
        for dep in notable:
            lines.append(
                f"- {dep.get('name', '')} — {dep.get('purpose', '')} "
                f"{_evidence_inline(dep.get('evidence'), language)}"
            )
    concerns = dependencies.get("concerns") or []
    if concerns:
        lines.append("")
        lines.append(label("deps.concerns", language))
        for concern in concerns:
            lines.append(
                f"- {concern.get('description', '')} "
                f"{_evidence_inline(concern.get('evidence'), language)}"
            )
    return lines


def _render_risks(analysis: dict, language: str = "en") -> list[str]:
    risks = analysis.get("risks", [])
    rows = [label("table.risks", language)]
    for risk in risks:
        rows.append(
            f"| {risk.get('severity', '')} | {risk.get('category', '')} | "
            f"{risk.get('description', '')} {_evidence_inline(risk.get('evidence'), language)} |"
        )
    if risks:
        rows.append("")
        for risk in risks:
            mitigation = risk.get("mitigation")
            if mitigation:
                rows.append(
                    f"- {label('risks.mitigation', language).format(cat=risk.get('category', ''))}: "
                    f"{mitigation}"
                )
    return rows if len(rows) > 1 else []


def _render_reading_order(analysis: dict, language: str = "en") -> list[str]:
    order = analysis.get("reading_order", [])
    lines: list[str] = []
    for step in order:
        lines.append(
            f"{step.get('step', '')}. `{step.get('target', '')}` — {step.get('why', '')}"
        )
    return lines


def _render_contributions(analysis: dict, language: str = "en") -> list[str]:
    opportunities = analysis.get("contribution_opportunities", [])
    lines: list[str] = []
    for opportunity in opportunities:
        related = " ".join(f"`{p}`" for p in (opportunity.get("related_files") or []))
        lines.append(
            f"- **{opportunity.get('area', '')}** ({opportunity.get('difficulty', '')}): "
            f"{opportunity.get('description', '')} "
            f"{_evidence_inline(opportunity.get('evidence'), language)}"
            + (f" — {label('contrib.touches', language)} {related}" if related else "")
        )
    return lines


def _render_unknowns(analysis: dict, language: str = "en") -> list[str]:
    unknowns = analysis.get("unknowns") or []
    if not unknowns:
        return [label("unknowns.none", language)]
    return [f"- {item}" for item in unknowns]


def _render_evidence_summary(evidence: dict, language: str = "en") -> list[str]:
    lines = [
        f"- {label('evid.total', language)} **{evidence.get('total_citations', 0)}**",
        f"- {label('evid.verified', language)} **{evidence.get('verified', 0)}**",
        f"- {label('evid.unverified', language)} **{evidence.get('unverified', 0)}**",
    ]
    unverified = evidence.get("unverified_list") or []
    for path in unverified:
        lines.append(f"  - `{path}`")
    return lines


def _evidence_inline(evidence: Any, language: str = "en") -> str:
    """Render an evidence array as inline backticked paths."""
    paths = [p for p in (evidence or []) if isinstance(p, str)]
    if not paths:
        return label("evidence.none", language)
    return "".join(f" [`{p}`]" for p in paths)


def _evidence_line(evidence: Any, language: str = "en") -> str:
    """Render evidence as its own line."""
    paths = [p for p in (evidence or []) if isinstance(p, str)]
    if not paths:
        return label("evidence.none", language)
    return f"{label('evidence.prefix', language)} " + " ".join(f"`{p}`" for p in paths)
