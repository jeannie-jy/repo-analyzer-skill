"""repo-analyzer command line interface.

Subcommands are the *tools* an agent (or a human) drives the pipeline with:

    repo-analyzer extract <url>          deterministic facts -> repo_facts.json
    repo-analyzer analyze <url>          full pipeline -> report.md + report.json
    repo-analyzer sample-code <url>      budgeted code sampling for LLM context
    repo-analyzer validate-report <f>    schema validation
    repo-analyzer verify-evidence <f>    citation checking

All five commands are live as of Phase 5.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import Settings
from .context.code_sampler import sample_code
from .errors import ConfigError, InputError, RepoAnalyzerError
from .github_client import GitHubClient
from .llm.openai_client import OpenAICompatClient
from .models import (
    ANALYSIS_FILENAME,
    FACTS_FILENAME,
    REPORT_FILENAME,
    REPORT_MD_FILENAME,
    RepoRef,
    RepoTree,
    TreeEntry,
)
from .pipeline.analyze import analyze
from .pipeline.evidence import verify_evidence
from .pipeline.facts import extract_facts
from .report.schema import validate_analysis


def _resolve_ref(value: str, *, ref: str | None = None) -> RepoRef:
    """Accept a GitHub URL or an existing local directory.

    Falls back to :meth:`RepoRef.from_local_path` only when the value
    looks like a real directory — garbage input keeps the URL error
    instead of a misleading "path does not exist". ``--ref`` selects a
    branch/tag/sha and applies to GitHub URLs only.
    """
    try:
        return RepoRef.from_url(value, ref=ref)
    except InputError as exc:
        if not Path(value).is_dir():
            raise
        if ref is not None:
            raise InputError("--ref applies to GitHub URLs only, not local paths")
        return RepoRef.from_local_path(value)


def _add_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    handler: Callable[[argparse.Namespace, Settings], int],
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(handler=handler)
    return parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-analyzer",
        description=(
            "Analyze a GitHub repository into a structured, evidence-based report."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(
        dest="command", required=True, metavar="<command>"
    )

    # --- Phase 3: deterministic extraction -------------------------------
    p = _add_command(
        sub, "extract",
        "Extract deterministic repository facts into repo_facts.json",
        _cmd_extract,
    )
    p.add_argument("url", help="GitHub repository URL (https://github.com/owner/repo)")
    p.add_argument("--ref", help="Branch / tag / sha to analyze (default: default branch)")
    p.add_argument("--output-dir", "-o", help="Override output directory")

    # --- Phase 4: LLM reasoning pipeline ----------------------------------
    p = _add_command(
        sub, "analyze",
        "Run the full analysis pipeline (extract + LLM reasoning)",
        _cmd_analyze,
    )
    p.add_argument("url", help="GitHub repository URL")
    p.add_argument("--ref", help="Branch / tag / sha to analyze (default: default branch)")
    p.add_argument("--output-dir", "-o", help="Override output directory")
    p.add_argument("--budget", type=int, help="Override code sampling token budget")

    p = _add_command(
        sub, "sample-code",
        "Fetch budgeted code samples for LLM context",
        _cmd_sample_code,
    )
    p.add_argument("url", help="GitHub repository URL")
    p.add_argument("--ref", help="Branch / tag / sha to analyze (default: default branch)")
    p.add_argument("--output-dir", "-o", help="Override output directory")
    p.add_argument("--budget", type=int, help="Override code sampling token budget")

    # --- Phase 5: report validation ---------------------------------------
    p = _add_command(
        sub, "validate-report",
        "Validate a report.json against the report schema",
        _cmd_validate_report,
    )
    p.add_argument("report", help="Path to report.json")

    p = _add_command(
        sub, "verify-evidence",
        "Verify citations in report.json against the repository tree",
        _cmd_verify_evidence,
    )
    p.add_argument("report", help="Path to report.json")
    p.add_argument("--facts", help="Path to repo_facts.json (default: next to the report)")

    # --- Phase 8: evaluation baseline --------------------------------------
    p = _add_command(
        sub, "eval",
        "Run the evaluation baseline against gold cases",
        _cmd_eval,
    )
    p.add_argument("cases", nargs="*", help="Case directories (default: evals/cases/*)")
    p.add_argument("--cases-root", default="evals/cases", help="Where case dirs live")
    p.add_argument("--output-dir", "-o", help="Override output directory (facts cache)")
    p.add_argument(
        "--judge", action="store_true",
        help="Also score existing reports with the LLM judge (needs LLM_API_KEY)",
    )
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Emit machine-readable results JSON")

    return parser


def _cmd_extract(args: argparse.Namespace, settings: Settings) -> int:
    ref = _resolve_ref(args.url, ref=args.ref)
    output_dir = args.output_dir or settings.output_dir
    client = GitHubClient(settings)
    facts = extract_facts(client, ref, output_dir=output_dir)
    path = ref.workdir(output_dir) / FACTS_FILENAME
    langs = ", ".join(l.name for l in facts.languages.languages[:5]) or "n/a"
    print(f"Extracted facts: {path}")
    print(f"  repo:        {ref.api_path} ({facts.repo.get('branch')} @ {(facts.repo.get('ref_sha') or '?')[:10]})")
    print(f"  languages:   {langs}")
    print(f"  files:       {facts.files.total_files} (tree truncated: {facts.tree.truncated})")
    print(f"  manifests:   {len(facts.manifests)}")
    print(f"  entrypoints: {len(facts.entrypoints)} candidates")
    print(f"  deps:        {len(facts.dependencies.direct)} direct")
    print(f"  warnings:    {len(facts.warnings)}")
    for warning in facts.warnings:
        print(f"    - {warning}")
    return 0


def _cmd_analyze(args: argparse.Namespace, settings: Settings) -> int:
    settings.require_llm()  # ConfigError -> exit 2, fail fast before any API call
    if args.budget:
        settings = replace(settings, token_budget=args.budget)
    ref = _resolve_ref(args.url, ref=args.ref)
    output_dir = args.output_dir or settings.output_dir
    client = GitHubClient(settings)
    llm = OpenAICompatClient(settings)
    result = analyze(
        client, llm, ref, output_dir=output_dir, budget=settings.token_budget
    )

    sections = sorted(
        k for k in ("overview", "architecture", "core_modules", "entry_points",
                    "risks", "contribution_opportunities") if k in result.analysis
    )
    sample = result.sample_manifest
    workdir = ref.workdir(output_dir)
    report_path = workdir / REPORT_FILENAME
    md_path = workdir / REPORT_MD_FILENAME
    print(f"Analysis written: {workdir / ANALYSIS_FILENAME}")
    print(f"Report written:   {report_path}")
    print(f"  markdown:    {md_path}")
    print(f"  model:       {result.model}")
    print(f"  sections:    {', '.join(sections) or 'n/a'}")
    print(f"  code sample: {len(sample['files'])} files, "
          f"{sample['total_token_estimate']:,} / {sample['budget']:,} tokens")
    evidence = result.report.get("evidence_summary", {})
    print(f"  grounding:   {evidence.get('verified', 0)}/"
          f"{evidence.get('total_citations', 0)} citations verified")
    print(f"  unknowns:    {len(result.analysis.get('unknowns', []))}")
    for warning in result.warnings:
        print(f"  warning:     {warning}")
    return 0


def _cmd_sample_code(args: argparse.Namespace, settings: Settings) -> int:
    ref = _resolve_ref(args.url, ref=args.ref)
    output_dir = args.output_dir or settings.output_dir
    budget = args.budget or settings.token_budget
    client = GitHubClient(settings)
    facts = extract_facts(client, ref, output_dir=output_dir)
    branch = facts.repo.get("branch") or "main"
    sample = sample_code(client, ref, branch, facts, budget=budget)
    manifest = sample.to_manifest()

    print(f"Sampled {len(manifest['files'])} files "
          f"({manifest['total_token_estimate']:,} / {budget:,} tokens):")
    for file in manifest["files"]:
        print(f"  {file['path']:45s} ~{file['token_estimate']:>6,} tokens  {file['reason']}")
    for entry in manifest["skipped"][:10]:
        print(f"  skipped: {entry}")
    if len(manifest["skipped"]) > 10:
        print(f"  ... and {len(manifest['skipped']) - 10} more skipped")
    return 0


def _cmd_validate_report(args: argparse.Namespace, settings: Settings) -> int:
    data = _load_json(args.report)
    result = validate_analysis(data.get("analysis", {}))
    if result.valid:
        print(f"Report is valid: {args.report}")
        return 0
    print(
        f"Report is INVALID - {len(result.errors)} violation(s): "
        f"{args.report}",
        file=sys.stderr,
    )
    for error in result.errors:
        print(f"  - {error}", file=sys.stderr)
    return 1


def _cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    from .evals import run_all, run_case

    output_dir = args.output_dir or settings.output_dir
    client = GitHubClient(settings)
    llm = None
    if args.judge:
        settings.require_llm()
        llm = OpenAICompatClient(settings)

    cases = args.cases or [str(Path(args.cases_root))]
    results = [
        run_case(client, c, output_dir=output_dir, llm=llm)
        if (Path(c) / "repo.json").is_file()
        else run_all(client, c, output_dir=output_dir, llm=llm)
        for c in cases
    ]
    results = [r for sub in results for r in (sub if isinstance(sub, list) else [sub])]

    if args.as_json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
        return 0

    for r in results:
        print(f"\n== {r.case} ==")
        s, e = r.structure, r.entrypoints
        print(f"  structure:  {s['hits']}/{s['expected']} gold paths found "
              f"({s['accuracy']:.0%})")
        if s["missing_paths"]:
            print(f"    missing:   {', '.join(s['missing_paths'])}")
        print(f"  entrypoints: P={e['precision']:.2f} R={e['recall']:.2f} "
              f"F1={e['f1']:.2f}  (gold {e['gold_count']}, found {e['predicted_count']})")
        if e["false_negatives"]:
            print(f"    missed:    {', '.join(e['false_negatives'])}")
        if e["false_positives"]:
            print(f"    extra:     {', '.join(e['false_positives'])}")
        if r.grounding:
            g = r.grounding
            print(f"  grounding:  {g['verified']}/{g['total_citations']} verified "
                  f"(hallucination {g['hallucination_rate']:.0%})")
        else:
            print("  grounding:  no report.json yet (run analyze first)")
        if r.judge:
            j = r.judge
            print(f"  judge:      coverage {j['coverage']} grounding {j['grounding']} "
                  f"correctness {j['correctness']} actionability {j['actionability']} "
                  f"| usefulness {j['usefulness']}")
            if j["comments"]:
                print(f"    comments:  {j['comments'][:200]}")
    return 0


def _cmd_verify_evidence(args: argparse.Namespace, settings: Settings) -> int:
    data = _load_json(args.report)
    facts_path = Path(args.facts) if args.facts else Path(args.report).parent / FACTS_FILENAME
    facts = _load_json(str(facts_path))
    tree = RepoTree(
        entries=[TreeEntry(**e) for e in facts.get("tree", {}).get("entries", [])]
    )
    evidence = verify_evidence(data.get("analysis", {}), tree)

    print(f"Citations: {evidence.total_citations} total, "
          f"{evidence.verified} verified, {evidence.unverified} unverified "
          f"(grounding {evidence.grounding_ratio:.0%})")
    for path in evidence.unverified_list:
        print(f"  unverified: {path}")
    return 0


def _load_json(path: str) -> dict:
    """Load a JSON artifact, raising InputError on unreadable/invalid files."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{path} does not contain a JSON object")
    return data


def _cmd_not_implemented(args: argparse.Namespace, settings: Settings) -> int:
    print(
        f"Command '{args.command}' is not implemented yet - "
        "see the phase roadmap in docs/ARCHITECTURE.md.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    handler: Callable[[argparse.Namespace, Settings], int] = args.handler
    try:
        return handler(args, settings)
    except InputError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except RepoAnalyzerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
