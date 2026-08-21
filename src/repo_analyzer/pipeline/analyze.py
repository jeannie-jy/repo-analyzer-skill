"""Orchestrate the full pipeline: facts -> sample -> LLM reasoning.

This is the CLI-driven twin of the agent-driven workflow in SKILL.md:
same extraction, same prompts, same contract — the only difference is
that ``LLMClient`` stands in for the agent's own reasoning.

Outputs under <output_dir>/repos/<owner>/<repo>/:
- ``repo_facts.json`` (from :mod:`repo_analyzer.pipeline.facts`)
- ``sample_manifest.json`` (what was shown to the LLM, without contents)
- ``analysis.json`` (the LLM's structured reasoning, unvalidated —
  Phase 5 validates it against the report schema)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import __version__
from ..context.code_sampler import sample_code
from ..errors import LLMError
from ..github_client import GitHubClient
from ..llm.base import LLMClient
from ..llm.prompts import build_analysis_messages
from ..models import (
    ANALYSIS_FILENAME,
    FACTS_SCHEMA_VERSION,
    SAMPLE_MANIFEST_FILENAME,
    RepoFacts,
    RepoRef,
    TOOL_NAME,
)
from .facts import extract_facts


@dataclass(frozen=True)
class AnalysisOutput:
    """The full pipeline result: parsed reasoning plus audit trail."""

    repo: dict
    schema_version: str
    model: str
    analysis: dict
    sample_manifest: dict
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
    """Run extract -> sample -> LLM reasoning and write the artifacts."""
    facts = extract_facts(client, ref, output_dir=output_dir, fetch_raw_fn=fetch_raw_fn)
    branch = facts.repo.get("branch") or "main"

    sample = sample_code(client, ref, branch, facts, budget=budget)
    messages = build_analysis_messages(facts, sample, prompt_dir=prompt_dir)
    response = llm.complete(messages)
    parsed = _parse_json_response(response)

    output = AnalysisOutput(
        repo=dict(facts.repo),
        schema_version=FACTS_SCHEMA_VERSION,
        model=getattr(getattr(llm, "settings", None), "llm_model", "unknown"),
        analysis=parsed,
        sample_manifest=sample.to_manifest(),
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
    return output


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
