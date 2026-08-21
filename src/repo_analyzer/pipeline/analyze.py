"""Orchestrate the full pipeline: facts -> sample -> LLM reasoning -> report.

This is the CLI-driven twin of the agent-driven workflow in SKILL.md:
same extraction, same prompts, same contract — the only difference is
that ``LLMClient`` stands in for the agent's own reasoning.

Outputs under <output_dir>/repos/<owner>/<repo>/:
- ``repo_facts.json`` (from :mod:`repo_analyzer.pipeline.facts`)
- ``sample_manifest.json`` (what was shown to the LLM, without contents)
- ``analysis.json`` (the validated LLM reasoning — audit trail)
- ``report.json`` (analysis + evidence summary, schema-validated)
- ``report.md`` (deterministic English markdown render)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..context.code_sampler import sample_code
from ..errors import LLMError
from ..github_client import GitHubClient
from ..llm.base import LLMClient, LLMMessage
from ..llm.prompts import build_analysis_messages
from ..models import (
    ANALYSIS_FILENAME,
    FACTS_SCHEMA_VERSION,
    REPORT_FILENAME,
    REPORT_MD_FILENAME,
    SAMPLE_MANIFEST_FILENAME,
    RepoFacts,
    RepoRef,
)
from ..report.render import render_markdown
from ..report.schema import REPORT_SCHEMA_VERSION, assert_valid, validate_analysis
from .evidence import verify_evidence
from .facts import extract_facts

# How many times we let the LLM repair its own contract violations before
# failing. One repair is cheap and fixes most drift (missing fields,
# wrong types); two keeps worst-case latency and cost bounded.
MAX_REPAIR_ATTEMPTS = 1


@dataclass(frozen=True)
class AnalysisOutput:
    """The full pipeline result: validated reasoning plus artifacts."""

    repo: dict
    schema_version: str
    model: str
    analysis: dict
    sample_manifest: dict
    report: dict
    report_md: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(
    client: GitHubClient,
    llm: LLMClient,
    ref: RepoRef,
    *,
    output_dir: str | Path,
    budget: int,
    fetch_raw_fn: Callable[[RepoRef, str, str], str] | None = None,
    prompt_dir: str | Path | None = None,
) -> AnalysisOutput:
    """Run extract -> sample -> LLM reasoning -> validate -> repair -> report.

    The LLM output is gated by the report schema. A contract violation
    starts a repair round: the violations are sent back to the LLM (its
    own output included as the assistant turn) and it must return the
    complete corrected JSON. Only when the repair still fails does the
    pipeline raise ``ReportValidationError`` instead of producing a
    report that cannot be trusted.
    """
    facts = extract_facts(client, ref, output_dir=output_dir, fetch_raw_fn=fetch_raw_fn)
    branch = facts.repo.get("branch") or "main"

    sample = sample_code(client, ref, branch, facts, budget=budget)
    messages = build_analysis_messages(facts, sample, prompt_dir=prompt_dir)
    response = llm.complete(messages)
    parsed = _parse_json_response(response)

    for _ in range(MAX_REPAIR_ATTEMPTS):
        result = validate_analysis(parsed)
        if result.valid:
            break
        repair = _repair_messages(messages, response, result.errors)
        response = llm.complete(repair)
        parsed = _parse_json_response(response)
    assert_valid(parsed)  # ReportValidationError if repair also failed

    evidence = verify_evidence(parsed, facts.tree)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "repo": dict(facts.repo),
        "model": getattr(getattr(llm, "settings", None), "llm_model", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis": parsed,
        "evidence_summary": evidence.to_dict(),
        "warnings": list(facts.warnings),
    }
    report_md = render_markdown(report)

    output = AnalysisOutput(
        repo=dict(facts.repo),
        schema_version=FACTS_SCHEMA_VERSION,
        model=report["model"],
        analysis=parsed,
        sample_manifest=sample.to_manifest(),
        report=report,
        report_md=report_md,
        warnings=list(facts.warnings),
    )

    workdir = ref.workdir(output_dir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / ANALYSIS_FILENAME).write_text(
        json.dumps(output.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (workdir / SAMPLE_MANIFEST_FILENAME).write_text(
        json.dumps(sample.to_manifest(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (workdir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (workdir / REPORT_MD_FILENAME).write_text(report_md, encoding="utf-8")
    return output


def _repair_messages(
    original: list[LLMMessage], bad_response: str, violations: list[str]
) -> list[LLMMessage]:
    """Build the repair turn: original context, the bad output as the
    assistant turn, then the violations as a corrective instruction.

    The facts digest and code sample are NOT repeated — the LLM already
    saw them in this conversation; only the correction is new, which
    keeps the repair cheap and provider-cache friendly.
    """
    return [
        *original,
        {"role": "assistant", "content": bad_response},
        {
            "role": "user",
            "content": (
                "Your previous response failed schema validation with these "
                "errors:\n"
                + "\n".join(f"- {v}" for v in violations)
                + "\n\nFix every error and reply with the COMPLETE corrected "
                "JSON object - all 13 top-level keys, correct types, nothing "
                "missing, no commentary, no markdown fences."
            ),
        },
    ]


def _parse_json_response(response: str) -> dict:
    """Parse the LLM's reply into a dict, tolerating markdown fences.

    Falls back to the outermost JSON object when the model wrapped the
    output in prose (common with smaller models). Raises ``LLMError``
    with a snippet of the response when nothing parses.
    """
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMError(
                    "LLM returned invalid JSON: could not parse the "
                    f"response. First 200 chars: {text[:200]!r}"
                ) from exc
        else:
            raise LLMError(
                "LLM returned no JSON object at all. "
                f"First 200 chars: {text[:200]!r}"
            ) from None
    if not isinstance(parsed, dict):
        raise LLMError(
            f"LLM returned JSON that is not an object: {type(parsed).__name__}."
        )
    return parsed
