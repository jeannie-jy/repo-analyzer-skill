"""Deterministic digest annex: the verified numbers a report may restate.

Claims restating digest-verified numbers (commit counts, file sizes,
line counts, open PR/issue counts, contributor commits) have no file
whose content proves them — the numbers are verified by the pipeline,
not by any path. The report therefore carries a ``digest_facts`` block
computed from ``RepoFacts`` (never by the LLM) and renders it as the
"Verified Facts" section, so the judge and any reader can check such
claims against ground truth inside the report itself.

The annex reads the same ``RepoFacts`` fields the facts digest renders
(:func:`repo_analyzer.llm.prompts.render_facts_digest`), so the prompt
and the report cannot drift. Rendering is deterministic: same facts,
same section, byte for byte.
"""

from __future__ import annotations

from typing import Any

from ..models import RepoFacts
from .labels import label

SECTION_TITLE = "Verified Facts (pipeline-computed)"

# Covers the sampler's largest-file tier (extract.file_stats caps at 15;
# the sampler skips tests/vendored and sends each remaining entry's byte
# count to the LLM via the sample reason — the annex must list every
# entry the LLM could restate, so the cap matches the extractor's, not
# the digest's top-8 view).
_LARGEST_FILES_CAP = 15


def section_title(language: str = "en") -> str:
    """The section title in ``language``; zh keeps the English anchor
    ("Verified Facts") so the prompt contract and the judge rubric —
    which both name the section — stay literally true under either."""
    return label("section.verified_facts", language)


def build_digest_facts(facts: RepoFacts) -> dict[str, Any]:
    """Serialize the digest-verified numbers into a report annex block."""
    m = facts.metadata
    g = facts.git
    f = facts.files
    return {
        "metadata": {
            "stars": m.stars,
            "forks": m.forks,
            "open_issues_count": m.open_issues_count,
        },
        "languages": [
            {"name": lang.name, "percentage": lang.percentage, "bytes": lang.bytes}
            for lang in facts.languages.languages
        ],
        "git": {
            "last_commit_at": g.last_commit_at,
            "commits_last_30d": g.commits_last_30d,
            "commits_30d_capped": g.commits_30d_capped,
            "open_issues": g.open_issues,
            "open_pulls": g.open_pulls,
            "top_contributors": [
                {"login": c.login, "contributions": c.contributions}
                for c in g.top_contributors
            ],
        },
        "files": {
            "total_files": f.total_files,
            "total_bytes": f.total_bytes,
            "files_by_extension": dict(f.files_by_extension),
            "largest_files": [
                {
                    "path": e.path,
                    "size_bytes": e.size_bytes,
                    # What makes "core.py (147,845 B / 3,799 lines)" checkable.
                    "lines": f.line_counts.get(e.path),
                }
                for e in f.largest_files[:_LARGEST_FILES_CAP]
            ],
            "line_counts": dict(f.line_counts),
        },
    }


def render_digest_facts(annex: dict[str, Any], language: str = "en") -> list[str]:
    """Markdown body lines for the Verified Facts section.

    The two issue counts are labeled by their endpoints and never merged:
    repo metadata counts PRs, the issues search does not (a repo can show
    87 vs 0 and be correct). ``(capped)`` marks a 30-day commit count that
    hit the extraction cap. Numbers, ``?``, and the ``B`` unit render
    identically under any language.
    """
    lines: list[str] = []

    meta = annex.get("metadata") or {}
    if meta:
        parts = [
            f"{_num(meta.get('stars'))} {label('digest.stars', language)}",
            f"{_num(meta.get('forks'))} {label('digest.forks', language)}",
            f"{_num(meta.get('open_issues_count'))} "
            f"{label('digest.open_issues_meta', language)}",
        ]
        lines.append(f"- {label('digest.metadata', language)} {' | '.join(parts)}")

    languages = annex.get("languages")
    if languages:
        langs = "; ".join(
            f"{lang['name']} {lang['percentage']:.1f}% "
            f"({_num(lang.get('bytes'))} {label('digest.bytes', language)})"
            for lang in languages
        )
        lines.append(f"- {label('digest.languages', language)} {langs}")

    git = annex.get("git") or {}
    if git:
        parts: list[str] = []
        if git.get("last_commit_at"):
            parts.append(f"{label('digest.last_commit', language)} {git['last_commit_at']}")
        commits = git.get("commits_last_30d")
        if commits is not None:
            capped = (
                f" {label('digest.capped', language)}"
                if git.get("commits_30d_capped")
                else ""
            )
            parts.append(f"{_num(commits)} {label('digest.commits_30d', language)}{capped}")
        parts.append(
            f"{label('digest.open_issues_search', language)} "
            f"{_num(git.get('open_issues'))}"
        )
        if git.get("open_pulls") is not None:
            parts.append(f"{label('digest.open_prs', language)} {_num(git['open_pulls'])}")
        top = git.get("top_contributors")
        if top:
            names = ", ".join(
                f"{c['login']} ({_num(c.get('contributions'))})" for c in top
            )
            parts.append(f"{label('digest.top_contributors', language)} {names}")
        lines.append(f"- {label('digest.git', language)} {' | '.join(parts)}")

    files = annex.get("files") or {}
    if files:
        parts = []
        if files.get("total_files") is not None:
            parts.append(f"{_num(files['total_files'])} {label('digest.files_count', language)}")
        if files.get("total_bytes") is not None:
            parts.append(f"{_num(files['total_bytes'])} {label('digest.bytes', language)}")
        largest = files.get("largest_files")
        if largest:
            entries = []
            for entry in largest:
                size = f"{_num(entry.get('size_bytes'))} {label('digest.bytes_unit', language)}"
                lines_count = entry.get("lines")
                if lines_count is not None:
                    entries.append(
                        f"{entry.get('path', '?')} ({size}, "
                        f"{_num(lines_count)} {label('digest.lines', language)})"
                    )
                else:
                    entries.append(f"{entry.get('path', '?')} ({size})")
            parts.append(f"{label('digest.largest', language)} " + ", ".join(entries))
        lines.append(f"- {label('digest.files', language)} {' | '.join(parts)}")

    return lines


def _num(value: Any) -> str:
    """Comma-group a number; '?' for unknown (degraded facts)."""
    if value is None:
        return "?"
    return f"{int(value):,}"
