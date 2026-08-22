"""Evaluation baseline: deterministic metrics plus an optional LLM judge.

Metrics (ARCHITECTURE.md section 10), all keyed off a gold case:

- ``structure`` — the extracted tree contains the gold ``expected_paths``
  (a hand-picked subset that matters, not the whole tree).
- ``entrypoints`` — precision / recall / F1 of the deterministic entry
  point candidates against the gold entry point paths.
- ``grounding`` / ``hallucination`` — citation verification reusing
  :func:`verify_evidence`; hallucination rate is the unverified share.
- ``judge`` — LLM-as-judge rubric (coverage / grounding / correctness /
  actionability) plus usefulness, 1-5 each.

Case layout: ``evals/cases/<repo>/{repo.json, gold.json, README.md}``.
``repo.json`` pins a url + ref so every run is reproducible.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .context.code_sampler import sample_code
from .errors import InputError
from .github_client import GitHubClient
from .llm.base import LLMClient
from .models import REPORT_FILENAME, RepoFacts, RepoRef, RepoTree
from .pipeline.analyze import _parse_json_response
from .pipeline.facts import extract_facts

GOLD_FILENAME = "gold.json"
REPO_FILENAME = "repo.json"

_JUDGE_SYSTEM = """\
You are an evaluation judge for repository analysis reports. Score the
report on four criteria and overall usefulness, each 1-5 (5 = best):

- coverage: does it address all major aspects of this repository
  (purpose, architecture, entry points, risks, contribution paths)?
- grounding: are claims tied to the cited evidence file paths, with no
  unsupported assertions? Evidence must directly support its claim: the
  cited file's content shows the claim itself. A citation that merely
  implies the claim (the file relates, but its content does not prove
  it) counts against grounding.
- correctness: are the technical claims accurate for this codebase
  (no invented APIs, wrong data flows, or guessed numbers)?
- actionability: are the risks and contribution opportunities concrete
  enough to act on (specific files, specific changes)?
- usefulness: overall, how well does this report equip a newcomer to
  understand and contribute to the codebase?

Return ONLY a JSON object, no commentary:
{"coverage": 1-5, "grounding": 1-5, "correctness": 1-5,
 "actionability": 1-5, "usefulness": 1-5, "comments": "..."}
"""


@dataclass(frozen=True)
class CaseResult:
    """Metrics for one gold case."""

    case: str
    repo: dict
    structure: dict
    entrypoints: dict
    grounding: dict | None
    judge: dict | None

    def to_dict(self) -> dict:
        return {
            "case": self.case,
            "repo": self.repo,
            "structure": self.structure,
            "entrypoints": self.entrypoints,
            "grounding": self.grounding,
            "judge": self.judge,
        }


def load_case(case_dir: str | Path) -> dict:
    """Read and sanity-check a gold case directory."""
    directory = Path(case_dir)
    repo_file = directory / REPO_FILENAME
    gold_file = directory / GOLD_FILENAME
    if not repo_file.is_file() or not gold_file.is_file():
        raise InputError(
            f"Not an eval case: {directory} (missing {REPO_FILENAME} or {GOLD_FILENAME})"
        )
    repo = json.loads(repo_file.read_text(encoding="utf-8"))
    gold = json.loads(gold_file.read_text(encoding="utf-8"))
    if not isinstance(repo, dict) or not repo.get("url"):
        raise InputError(f"{repo_file}: needs a \"url\" field")
    if not isinstance(gold, dict) or not isinstance(gold.get("entrypoints"), list):
        raise InputError(f"{gold_file}: needs an \"entrypoints\" array")
    gold_paths = []
    for entry in gold["entrypoints"]:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path:
            raise InputError(
                f"{gold_file}: every entrypoint needs a non-empty \"path\""
            )
        gold_paths.append(path)
    return {"directory": directory, "repo": repo, "gold": gold}


def structure_accuracy(tree: RepoTree, expected_paths: list[str]) -> dict:
    """Share of gold paths present in the extracted tree."""
    tree_paths = {e.path for e in tree.entries}
    hits = [p for p in expected_paths if p in tree_paths]
    misses = [p for p in expected_paths if p not in tree_paths]
    return {
        "expected": len(expected_paths),
        "hits": len(hits),
        "misses": len(misses),
        "accuracy": len(hits) / len(expected_paths) if expected_paths else 1.0,
        "missing_paths": misses,
    }


def entrypoint_metrics(facts: RepoFacts, gold_paths: list[str]) -> dict:
    """Precision / recall / F1 of deterministic candidates vs gold."""
    predicted = {c.path for c in facts.entrypoints if c.path}
    gold_set = set(gold_paths)
    true_positives = predicted & gold_set
    precision = len(true_positives) / len(predicted) if predicted else 0.0
    recall = len(true_positives) / len(gold_set) if gold_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "gold_count": len(gold_set),
        "predicted_count": len(predicted),
        "true_positives": sorted(true_positives),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_negatives": sorted(gold_set - predicted),
        "false_positives": sorted(predicted - gold_set),
    }


def grounding_metrics(report: dict) -> dict | None:
    """Unverified-citation share from an existing report.json (if any)."""
    summary = report.get("evidence_summary")
    if not isinstance(summary, dict):
        return None
    total = summary.get("total_citations", 0)
    unverified = summary.get("unverified", 0)
    return {
        "total_citations": total,
        "verified": summary.get("verified", 0),
        "unverified": unverified,
        "hallucination_rate": unverified / total if total else 0.0,
        "unverified_list": summary.get("unverified_list", []),
    }


def judge_report(llm: LLMClient, report_md: str, case_name: str, url: str) -> dict:
    """Score an existing report.md with the rubric (LLM-as-judge)."""
    user = (
        f"Repository: {case_name} ({url})\n\n"
        f"Report:\n{report_md}\n\n"
        "Score each criterion and return the JSON object."
    )
    parsed = _parse_json_response(
        llm.complete([{"role": "system", "content": _JUDGE_SYSTEM},
                      {"role": "user", "content": user}])
    )
    scored = {}
    for key in ("coverage", "grounding", "correctness", "actionability", "usefulness"):
        value = parsed.get(key)
        if not isinstance(value, (int, float)) or not 1 <= value <= 5:
            raise InputError(f"Judge returned invalid {key}={value!r}")
        scored[key] = int(value)
    scored["comments"] = str(parsed.get("comments", ""))[:500]
    return scored


def run_case(
    client: GitHubClient,
    case_dir: str | Path,
    *,
    output_dir: str | Path,
    llm: LLMClient | None = None,
    fetch_raw_fn: Callable | None = None,
) -> CaseResult:
    """Extract facts for a pinned ref and score every deterministic metric."""
    case = load_case(case_dir)
    ref = RepoRef.from_url(case["repo"]["url"], ref=case["repo"].get("ref"))
    gold = case["gold"]
    facts = extract_facts(
        client, ref, output_dir=output_dir, fetch_raw_fn=fetch_raw_fn
    )

    grounding = None
    report_path = ref.workdir(output_dir) / REPORT_FILENAME
    if report_path.is_file():
        grounding = grounding_metrics(
            json.loads(report_path.read_text(encoding="utf-8"))
        )

    judge = None
    if llm is not None:
        md_path = ref.workdir(output_dir) / "report.md"
        if md_path.is_file():
            judge = judge_report(llm, md_path.read_text(encoding="utf-8"),
                                 ref.api_path, case["repo"]["url"])

    return CaseResult(
        case=case["directory"].name,
        repo={"url": case["repo"]["url"], "ref": case["repo"].get("ref")},
        structure=structure_accuracy(facts.tree, gold.get("expected_paths", [])),
        entrypoints=entrypoint_metrics(
            facts, [e["path"] for e in gold["entrypoints"]]
        ),
        grounding=grounding,
        judge=judge,
    )


def run_all(
    client: GitHubClient,
    cases_root: str | Path,
    *,
    output_dir: str | Path,
    llm: LLMClient | None = None,
    fetch_raw_fn: Callable | None = None,
) -> list[CaseResult]:
    """Run every ``evals/cases/*`` subdirectory and return per-case results."""
    root = Path(cases_root)
    results: list[CaseResult] = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (case_dir / REPO_FILENAME).is_file():
            continue  # not a case directory
        results.append(
            run_case(client, case_dir, output_dir=output_dir, llm=llm,
                     fetch_raw_fn=fetch_raw_fn)
        )
    return results
