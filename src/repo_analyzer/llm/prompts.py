"""Assemble LLM prompts from the fact base and the code sample.

The knowledge assets under ``skill/prompts/`` (architecture, code-flow,
risk-analysis, contribution) are the reasoning guidance — shared verbatim
by the agent-driven mode (SKILL.md) and the CLI-driven pipeline. The
output *contract* (evidence rules, JSON-only output, top-level shape)
lives here in code: it is the single source that Phase 5's schema
validates against.

``render_facts_digest`` is a curated digest of the fact base — numbers
are copied verbatim from the verified facts, never recomputed by the LLM.
"""

from __future__ import annotations

from pathlib import Path

from ..context.code_sampler import CodeSample
from ..models import RepoFacts
from .base import LLMMessage

_PROMPT_FILENAMES = (
    "architecture.md",
    "code-flow.md",
    "risk-analysis.md",
    "contribution.md",
)

DEFAULT_PROMPT_DIR = Path(__file__).resolve().parents[3] / "skill" / "prompts"

# Output contract — the invariant every analysis must satisfy. Kept in code
# (not in the markdown assets) so schema validation has one source of truth.
_OUTPUT_CONTRACT = """\
You are analyzing a GitHub repository for a newcomer. You receive:
1. a FACTS digest — verified by deterministic extraction, treat every
   number as ground truth and never recompute or second-guess it;
2. a CODE SAMPLE — actual file contents, referenced by exact path.

IRON RULES:
- The response MUST contain ALL of these top-level keys, never fewer,
  never renamed: overview, tech_stack, structure, architecture,
  core_modules, entry_points, execution_flow, key_files, dependencies,
  risks, reading_order, contribution_opportunities, unknowns.
- Every claim carries an "evidence" array of file paths that exist in the
  facts or the sample. Quote paths exactly as written in the digest.
- Evidence must be DIRECT: the cited file's content must itself show the
  claim (a class definition, a dependency entry, a registration call). A
  path that only relates to the claim without proving it is indirect
  evidence — replace it with the file that demonstrates the claim, or
  move the claim to "unknowns". A claim restating a verified fact from
  the digest is directly supported by the path the digest attributes it
  to.
- Never invent facts, numbers, or files. Anything unanswerable from the
  digest or sample goes into "unknowns".
- Never repeat or guess metadata the digest already provides (stars,
  file counts, language shares, dependency versions) — cite them.
- "confidence" on entry points combines the deterministic heuristic with
  what the sampled code shows; keep the deterministic value when the code
  gives no contrary signal.
- Output ONLY a single JSON object, no markdown fences, no commentary,
  following the section contracts below."""

_FALLBACK_SYSTEM_PROMPT = """\
You are analyzing a GitHub repository for a newcomer. You receive a facts
digest (verified ground truth) and a code sample. Produce a JSON analysis
with keys: overview, tech_stack, structure, architecture, core_modules,
entry_points, execution_flow, key_files, dependencies, risks,
reading_order, contribution_opportunities, unknowns. Every claim must
carry an "evidence" array of file paths from the digest or sample, and
the cited file's content must directly support the claim (not merely
relate to it); never invent facts; put unanswered questions in
"unknowns". Output only JSON."""


def load_prompt_sections(prompt_dir: str | Path | None = None) -> list[str]:
    """Read the reasoning guidance assets, in section order.

    Falls back to an embedded instruction set when the ``skill/``
    directory is not present (e.g. installed without the repo assets).
    """
    directory = Path(prompt_dir) if prompt_dir else DEFAULT_PROMPT_DIR
    sections: list[str] = []
    if directory.is_dir():
        for name in _PROMPT_FILENAMES:
            path = directory / name
            if path.is_file():
                sections.append(path.read_text(encoding="utf-8").strip())
    if not sections:
        sections = [_FALLBACK_SYSTEM_PROMPT]
    return sections


def build_analysis_messages(
    facts: RepoFacts,
    sample: CodeSample,
    *,
    prompt_dir: str | Path | None = None,
) -> list[LLMMessage]:
    """System message = contract + reasoning sections; user message =
    facts digest + code sample + task."""
    system = "\n\n".join([_OUTPUT_CONTRACT, *load_prompt_sections(prompt_dir)])
    user = "\n\n".join(
        [
            render_facts_digest(facts),
            render_sample(sample),
            "Produce the analysis JSON object now. Output ONLY the JSON.",
        ]
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_facts_digest(facts: RepoFacts) -> str:
    m = facts.metadata
    lines = [
        "=== REPOSITORY FACTS (verified by deterministic extraction - ground truth) ===",
        f"repo:  {facts.repo.get('owner')}/{facts.repo.get('repo')} "
        f"@ {facts.repo.get('branch')} (sha {str(facts.repo.get('ref_sha'))[:10] or '?'})",
        f"url:   {facts.repo.get('url')}",
    ]
    lines.append(
        f"metadata: {m.stars:,} stars | {m.forks:,} forks | {m.open_issues_count:,} "
        f"open issues | license: {m.license_name or 'n/a'} | "
        f"archived: {m.is_archived} | fork: {m.is_fork}"
    )
    if m.description:
        lines.append(f"description: {m.description}")
    if m.topics:
        lines.append(f"topics: {', '.join(m.topics)}")
    lines.append(f"created: {m.created_at or '?'} | last push: {m.pushed_at or '?'}")

    lines.append("\nLANGUAGES:")
    for lang in facts.languages.languages:
        lines.append(f"  {lang.name} {lang.percentage:.1f}% ({lang.bytes:,} bytes)")

    tree = facts.tree
    lines.append("\nLAYOUT (top level):")
    lines.append(f"  dirs:  {', '.join(tree.top_level_dirs) or 'n/a'}")
    lines.append(f"  files: {', '.join(tree.top_level_files) or 'n/a'}")
    lines.append(
        f"  tree: {len(tree.entries)} entries, truncated: {tree.truncated}"
    )

    if facts.manifests:
        lines.append("\nMANIFESTS:")
        for manifest in facts.manifests:
            lines.append(f"  {manifest.path} ({manifest.kind})")

    lines.append("\nDIRECT DEPENDENCIES:")
    if facts.dependencies.direct:
        for dep in facts.dependencies.direct:
            version = f" {dep.version}" if dep.version else ""
            lines.append(
                f"  {dep.category:8s} {dep.name}{version}  <- {dep.manifest}"
            )
    else:
        lines.append("  (none detected)")
    if facts.dependencies.unparseable:
        lines.append("UNPARSEABLE MANIFESTS:")
        for manifest in facts.dependencies.unparseable:
            lines.append(f"  {manifest.path}: {manifest.reason}")

    lines.append("\nENTRY POINT CANDIDATES (deterministic heuristics):")
    if facts.entrypoints:
        for c in facts.entrypoints:
            invocation = f"  inv: {c.invocation}" if c.invocation else ""
            lines.append(
                f"  - {c.path}  [{c.kind}]  conf {c.confidence:.2f}  "
                f"\"{c.heuristic}\"{invocation}"
            )
    else:
        lines.append("  (none detected)")

    g = facts.git
    lines.append("\nGIT ACTIVITY:")
    lines.append(
        f"  last commit: {g.last_commit_at or '?'} | "
        f"commits (30d): {g.commits_last_30d or 0}"
        f"{' (capped)' if g.commits_30d_capped else ''}"
    )
    if g.top_contributors:
        top = ", ".join(f"{c.login} ({c.contributions})" for c in g.top_contributors)
        lines.append(f"  top contributors: {top}")
    lines.append(
        f"  open issues: {g.open_issues} | open PRs: {g.open_pulls if g.open_pulls is not None else '?'}"
    )

    f = facts.files
    lines.append("\nFILES:")
    lines.append(
        f"  {f.total_files} files, {f.total_bytes:,} bytes (vendored excluded)"
    )
    if f.files_by_extension:
        ext_summary = ", ".join(f"{ext}: {n}" for ext, n in f.files_by_extension.items())
        lines.append(f"  extensions: {ext_summary}")
    if f.largest_files:
        largest = ", ".join(f"{e.path} ({e.size_bytes:,} B)" for e in f.largest_files[:8])
        lines.append(f"  largest: {largest}")
    if f.line_counts:
        lc = ", ".join(f"{path}: {n}" for path, n in f.line_counts.items())
        lines.append(f"  line counts (sampled): {lc}")

    r = facts.readme
    lines.append("\nREADME:")
    if r.excerpt:
        lines.append(f"  excerpt: {r.excerpt[:400]}".replace("\n", " "))
    if r.quickstart_commands:
        lines.append(f"  quickstart commands: {'; '.join(r.quickstart_commands)}")

    if facts.warnings:
        lines.append("\nWARNINGS (degraded facts in these areas):")
        for warning in facts.warnings:
            lines.append(f"  - {warning}")
    return "\n".join(lines)


def render_sample(sample: CodeSample) -> str:
    lines = [
        f"=== CODE SAMPLE (budget {sample.budget:,} tokens, "
        f"used {sample.total_token_estimate:,}) ==="
    ]
    for file in sample.files:
        fence = _fence_language(file.path)
        lines.append(
            f"\n### {file.path} (~{file.token_estimate:,} tokens) — {file.reason}"
        )
        lines.append(f"```{fence}")
        lines.append(file.content)
        lines.append("```")
    if sample.skipped:
        lines.append("\nSKIPPED (not in sample):")
        for entry in sample.skipped[:50]:
            lines.append(f"  - {entry}")
    return "\n".join(lines)


def _fence_language(path: str) -> str:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "go": "go",
        "rs": "rust",
        "java": "java",
        "toml": "toml",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "md": "markdown",
        "sh": "bash",
    }.get(suffix, suffix or "text")
