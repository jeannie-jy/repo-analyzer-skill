"""Evaluation metrics: gold cases, structure accuracy, entrypoint F1,
grounding/hallucination, and the LLM judge wrapper."""

from __future__ import annotations

import json

import pytest

from repo_analyzer.evals import (
    entrypoint_metrics,
    grounding_metrics,
    judge_report,
    load_case,
    structure_accuracy,
)
from repo_analyzer.errors import InputError
from repo_analyzer.models import (
    EntrypointCandidate,
    RepoFacts,
    RepoTree,
    TreeEntry,
)

from .fake_llm import FakeLLM


def _tree(paths: list[str]) -> RepoTree:
    return RepoTree(
        entries=[
            TreeEntry(path=p, type="blob", size=1, sha="s") for p in paths
        ]
    )


def _facts(entrypoint_paths: list[str]) -> RepoFacts:
    return RepoFacts(
        repo={"branch": "main"},
        entrypoints=[
            EntrypointCandidate(path=p, kind="cli", heuristic="test", confidence=0.9)
            for p in entrypoint_paths
        ],
    )


# --- structure accuracy -----------------------------------------------------


def test_structure_accuracy_hits_and_misses() -> None:
    tree = _tree(["src/main.py", "src/util.py", "README.md"])
    result = structure_accuracy(tree, ["src/main.py", "src/util.py", "missing.py"])
    assert result["hits"] == 2
    assert result["misses"] == 1
    assert result["missing_paths"] == ["missing.py"]
    assert result["accuracy"] == pytest.approx(2 / 3)


def test_structure_accuracy_empty_gold_is_perfect() -> None:
    assert structure_accuracy(_tree(["a.py"]), [])["accuracy"] == 1.0


# --- entrypoint F1 ----------------------------------------------------------


def test_entrypoint_f1_perfect_match() -> None:
    m = entrypoint_metrics(_facts(["a.py", "b.py"]), ["a.py", "b.py"])
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0


def test_entrypoint_f1_partial() -> None:
    m = entrypoint_metrics(_facts(["a.py", "noise.py"]), ["a.py", "b.py"])
    assert m["precision"] == pytest.approx(0.5)  # noise.py is extra
    assert m["recall"] == pytest.approx(0.5)  # b.py is missed
    assert m["f1"] == pytest.approx(0.5)
    assert m["false_negatives"] == ["b.py"]
    assert m["false_positives"] == ["noise.py"]


def test_entrypoint_f1_empty_gold() -> None:
    m = entrypoint_metrics(_facts(["a.py"]), [])
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
    assert m["f1"] == 0.0


# --- grounding / hallucination ----------------------------------------------


def test_grounding_metrics_from_evidence_summary() -> None:
    g = grounding_metrics(
        {
            "evidence_summary": {
                "total_citations": 10,
                "verified": 8,
                "unverified": 2,
                "unverified_list": ["ghost.py"],
            }
        }
    )
    assert g["hallucination_rate"] == pytest.approx(0.2)
    assert g["unverified_list"] == ["ghost.py"]


def test_grounding_metrics_absent_report() -> None:
    assert grounding_metrics({"analysis": {}}) is None


def test_grounding_metrics_zero_citations() -> None:
    g = grounding_metrics({"evidence_summary": {"total_citations": 0, "verified": 0, "unverified": 0}})
    assert g["hallucination_rate"] == 0.0


# --- gold case loading ------------------------------------------------------


def test_load_case_requires_repo_and_gold(tmp_path) -> None:
    with pytest.raises(InputError, match="Not an eval case"):
        load_case(tmp_path)

    (tmp_path / "gold.json").write_text(json.dumps({"entrypoints": [{"path": "a.py"}]}), encoding="utf-8")
    (tmp_path / "repo.json").write_text("{}", encoding="utf-8")
    with pytest.raises(InputError, match="url"):
        load_case(tmp_path)

    (tmp_path / "repo.json").write_text(json.dumps({"url": "https://github.com/x/y"}), encoding="utf-8")
    case = load_case(tmp_path)
    assert case["repo"]["url"] == "https://github.com/x/y"
    assert case["gold"]["entrypoints"] == [{"path": "a.py"}]

    (tmp_path / "gold.json").write_text(json.dumps({"entrypoints": ["a.py"]}), encoding="utf-8")
    with pytest.raises(InputError, match="path"):
        load_case(tmp_path)


# --- LLM judge --------------------------------------------------------------


def test_judge_report_parses_scores() -> None:
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "coverage": 4,
                    "grounding": 5,
                    "correctness": 3,
                    "actionability": 2,
                    "usefulness": 4,
                    "comments": "solid",
                }
            )
        ]
    )
    scores = judge_report(llm, "# Report\nfake", "x/y", "https://github.com/x/y")
    assert scores["coverage"] == 4
    assert scores["usefulness"] == 4
    assert scores["comments"] == "solid"
    # the judge saw the report and the rubric in its messages
    system = llm.calls[0][0]["content"]
    assert "coverage" in system and "usefulness" in system
    assert "directly support" in system
    assert "# Report" in llm.calls[0][1]["content"]


def test_judge_report_rejects_out_of_range_scores() -> None:
    llm = FakeLLM([json.dumps({"coverage": 9, "grounding": 5, "correctness": 5,
                               "actionability": 5, "usefulness": 5})])
    with pytest.raises(InputError, match="coverage"):
        judge_report(llm, "report", "x/y", "https://github.com/x/y")
