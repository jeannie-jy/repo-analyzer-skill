"""repo-analyzer command line interface.

Subcommands are the *tools* an agent (or a human) drives the pipeline with:

    repo-analyzer extract <url>          deterministic facts -> repo_facts.json
    repo-analyzer analyze <url>          full pipeline -> report.md + report.json
    repo-analyzer sample-code <url>      budgeted code sampling for LLM context
    repo-analyzer validate-report <f>    schema validation
    repo-analyzer verify-evidence <f>    citation checking

Phase 2: the command tree and error handling are live; handlers are stubs
that get wired to the pipeline in Phases 3-5.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from . import __version__
from .config import Settings
from .errors import ConfigError, InputError, RepoAnalyzerError


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
        _cmd_not_implemented,
    )
    p.add_argument("url", help="GitHub repository URL (https://github.com/owner/repo)")
    p.add_argument("--ref", help="Branch / tag / sha to analyze (default: default branch)")
    p.add_argument("--output-dir", "-o", help="Override output directory")

    # --- Phase 4: LLM reasoning pipeline ----------------------------------
    p = _add_command(
        sub, "analyze",
        "Run the full analysis pipeline (extract + LLM reasoning + report)",
        _cmd_not_implemented,
    )
    p.add_argument("url", help="GitHub repository URL")
    p.add_argument("--ref", help="Branch / tag / sha to analyze (default: default branch)")
    p.add_argument("--output-dir", "-o", help="Override output directory")
    p.add_argument("--budget", type=int, help="Override code sampling token budget")

    p = _add_command(
        sub, "sample-code",
        "Fetch budgeted code samples for LLM context",
        _cmd_not_implemented,
    )
    p.add_argument("url", help="GitHub repository URL")
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
