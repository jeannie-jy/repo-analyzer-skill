"""repo-analyzer command line interface.

Subcommands are the *tools* an agent (or a human) drives the pipeline with:

    repo-analyzer extract <url>          deterministic facts -> repo_facts.json
    repo-analyzer analyze <url>          full pipeline -> analysis.json
    repo-analyzer sample-code <url>      budgeted code sampling for LLM context
    repo-analyzer validate-report <f>    schema validation
    repo-analyzer verify-evidence <f>    citation checking

Phases 3-4: ``extract`` / ``analyze`` / ``sample-code`` are live; the
report-validation commands get wired in Phase 5.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import replace

from . import __version__
from .config import Settings
from .context.code_sampler import sample_code
from .errors import ConfigError, InputError, RepoAnalyzerError
from .github_client import GitHubClient
from .llm.openai_client import OpenAICompatClient
from .models import ANALYSIS_FILENAME, FACTS_FILENAME, RepoRef
from .pipeline.analyze import analyze
from .pipeline.facts import extract_facts


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
        _cmd_not_implemented,
    )
    p.add_argument("report", help="Path to report.json")

    p = _add_command(
        sub, "verify-evidence",
        "Verify citations in report.json against the repository tree",
        _cmd_not_implemented,
    )
    p.add_argument("report", help="Path to report.json")
    p.add_argument("--facts", help="Path to repo_facts.json (default: next to the report)")

    return parser


def _cmd_extract(args: argparse.Namespace, settings: Settings) -> int:
    ref = RepoRef.from_url(args.url, ref=args.ref)
    output_dir = args.output_dir or settings.output_dir
    client = GitHubClient(settings)
    facts = extract_facts(client, ref, output_dir=output_dir)
    path = ref.workdir(output_dir) / FACTS_FILENAME
    langs = ", ".join(l.name for l in facts.languages.languages[:5]) or "n/a"
    print(f"Extracted facts: {path}")
    print(f"  repo:        {ref.api_path} ({facts.repo.get('branch')} @ {facts.repo.get('ref_sha', '?')[:10]})")
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
    ref = RepoRef.from_url(args.url, ref=args.ref)
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
    path = ref.workdir(output_dir) / ANALYSIS_FILENAME
    print(f"Analysis written: {path}")
    print(f"  model:       {result.model}")
    print(f"  sections:    {', '.join(sections) or 'n/a'}")
    print(f"  code sample: {len(sample['files'])} files, "
          f"{sample['total_token_estimate']:,} / {sample['budget']:,} tokens")
    print(f"  unknowns:    {len(result.analysis.get('unknowns', []))}")
    for warning in result.warnings:
        print(f"  warning:     {warning}")
    return 0


def _cmd_sample_code(args: argparse.Namespace, settings: Settings) -> int:
    ref = RepoRef.from_url(args.url, ref=args.ref)
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
