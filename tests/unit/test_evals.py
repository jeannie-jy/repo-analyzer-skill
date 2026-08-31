"""Evaluation metrics: gold cases, structure accuracy, entrypoint F1,
grounding/hallucination, and the LLM judge wrapper."""

from __future__ import annotations

import json

import pytest

from repo_analyzer.evals import (
    _combine_judge,
    _judge_model_name,
    _median,
    entrypoint_metrics,
    grounding_metrics,
    judge_report,
    load_case,
    structure_accuracy,
)
from repo_analyzer.config import Settings
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
    # old-rubric output (no sections array) parses with sections == []
    assert scores["sections"] == []
    # the judge saw the report and the rubric in its messages
    system = llm.calls[0][0]["content"]
    assert "coverage" in system and "usefulness" in system
    assert "directly support" in system
    assert "Per-section scores" in system
    assert "# Report" in llm.calls[0][1]["content"]


def test_judge_rubric_mentions_verified_facts_and_keeps_directly_support() -> None:
    """The digest-annex exemption joined the rubric without loosening the
    direct-evidence rule that guards against invented citations."""
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "coverage": 5,
                    "grounding": 5,
                    "correctness": 5,
                    "actionability": 5,
                    "usefulness": 5,
                    "comments": "ok",
                }
            )
        ]
    )
    judge_report(llm, "report", "x/y", "https://github.com/x/y")
    system = llm.calls[0][0]["content"]
    assert "Verified Facts" in system
    assert "directly support" in system
    # zh reports judge the same: content language must not confuse the rubric
    assert "English or Chinese" in system


def test_judge_report_rejects_out_of_range_scores() -> None:
    llm = FakeLLM([json.dumps({"coverage": 9, "grounding": 5, "correctness": 5,
                               "actionability": 5, "usefulness": 5})])
    with pytest.raises(InputError, match="coverage"):
        judge_report(llm, "report", "x/y", "https://github.com/x/y")


def test_judge_report_parses_sections() -> None:
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "sections": [
                        {"name": "Overview", "grounding": 5, "correctness": 4,
                         "comments": "well supported"},
                        {"name": "Risks", "grounding": 2, "correctness": 3,
                         "comments": "thin"},
                    ],
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
    assert scores["sections"] == [
        {"name": "Overview", "grounding": 5, "correctness": 4,
         "comments": "well supported"},
        {"name": "Risks", "grounding": 2, "correctness": 3, "comments": "thin"},
    ]
    # flat five still parse alongside the per-section array
    assert scores["coverage"] == 4 and scores["usefulness"] == 4


def _judge_run(model: str, scores: dict) -> tuple[str, dict]:
    """A per-model judge run with the flat keys judge_report produces."""
    return model, {
        "coverage": scores.get("coverage", 4),
        "grounding": scores.get("grounding", 4),
        "correctness": scores.get("correctness", 4),
        "actionability": scores.get("actionability", 4),
        "usefulness": scores.get("usefulness", 4),
        "comments": scores.get("comments", ""),
        "sections": scores.get("sections", []),
    }


# --- judge ensemble ---------------------------------------------------------


def test_median_odd_and_even() -> None:
    assert _median([5, 3, 4]) == 4
    assert _median([4, 5]) == 4.5  # even count: mid-two mean (baseline.md style)
    assert _median([2, 5, 5]) == 5
    assert _median([1, 2, 3, 4]) == 2.5


def test_combine_judge_single_model_is_identity() -> None:
    run = _judge_run("deepseek-v4-flash", {
        "coverage": 4, "grounding": 5, "comments": "ok",
        "sections": [{"name": "Overview", "grounding": 5, "correctness": 4,
                      "comments": "good"}],
    })
    combined = _combine_judge([run])
    assert combined["coverage"] == 4
    assert combined["grounding"] == 5
    assert combined["comments"] == "deepseek-v4-flash: ok"
    assert combined["sections"] == [
        {"name": "Overview", "grounding": 5, "correctness": 4,
         "comments": "good"}]
    assert combined["models"] == [
        {"model": "deepseek-v4-flash", "coverage": 4, "grounding": 5,
         "correctness": 4, "actionability": 4, "usefulness": 4}]


def test_combine_judge_two_models_takes_median_and_keeps_both() -> None:
    a = _judge_run("deepseek-v4-flash", {
        "coverage": 4, "grounding": 5, "correctness": 4, "actionability": 4,
        "usefulness": 5, "comments": "model A",
        "sections": [
            {"name": "Overview", "grounding": 5, "correctness": 4, "comments": "A1"},
            {"name": "Risks", "grounding": 3, "correctness": 5, "comments": "A2"},
        ],
    })
    b = _judge_run("gpt-4o-mini", {
        "coverage": 5, "grounding": 4, "correctness": 4, "actionability": 5,
        "usefulness": 4, "comments": "model B",
        "sections": [
            {"name": "Overview", "grounding": 4, "correctness": 5, "comments": "B1"},
            {"name": "Risks", "grounding": 5, "correctness": 3, "comments": "B2"},
        ],
    })
    combined = _combine_judge([a, b])
    assert combined["coverage"] == 4.5
    assert combined["grounding"] == 4.5
    assert combined["correctness"] == 4
    assert combined["actionability"] == 4.5
    assert combined["usefulness"] == 4.5
    assert combined["comments"] == "deepseek-v4-flash: model A | gpt-4o-mini: model B"
    assert combined["sections"] == [
        {"name": "Overview", "grounding": 4.5, "correctness": 4.5,
         "comments": "A1 | B1"},
        {"name": "Risks", "grounding": 4, "correctness": 4,
         "comments": "A2 | B2"},
    ]
    assert [m["model"] for m in combined["models"]] == [
        "deepseek-v4-flash", "gpt-4o-mini"]
    assert combined["models"][0]["coverage"] == 4  # per-model scores kept


def test_combine_judge_three_models_takes_true_median() -> None:
    runs = [
        _judge_run(m, {"coverage": v, "grounding": v,
                       "correctness": v, "actionability": v, "usefulness": v})
        for m, v in [("a", 3), ("b", 5), ("c", 4)]
    ]
    combined = _combine_judge(runs)
    assert combined["coverage"] == 4  # median of 3, 5, 4
    assert combined["grounding"] == 4


def test_combine_judge_aligns_sections_by_name_and_skips_empty_comments() -> None:
    a = _judge_run("a", {"sections": [
        {"name": "Overview", "grounding": 5, "correctness": 5, "comments": "A"}]})
    b = _judge_run("b", {"sections": [
        {"name": "Overview", "grounding": 3, "correctness": 3, "comments": ""},
        {"name": "Unknowns", "grounding": 2, "correctness": 4, "comments": "B"}]})
    combined = _combine_judge([a, b])
    assert [s["name"] for s in combined["sections"]] == ["Overview", "Unknowns"]
    overview = combined["sections"][0]
    assert overview["grounding"] == 4  # median of 5, 3
    assert overview["comments"] == "A"  # empty comment dropped
    unknowns = combined["sections"][1]
    assert unknowns["grounding"] == 2  # only b scored it
    assert unknowns["comments"] == "B"


def test_judge_report_retries_parse_failures() -> None:
    """A truncated reasoning-model reply must not abort the eval run."""
    from repo_analyzer.errors import LLMError

    good = json.dumps({"coverage": 4, "grounding": 5, "correctness": 4,
                       "actionability": 4, "usefulness": 4})
    llm = FakeLLM([LLMError("invalid JSON: truncated"), good])
    scores = judge_report(llm, "report", "x/y", "https://github.com/x/y")
    assert scores["coverage"] == 4
    assert len(llm.calls) == 2  # first reply failed, second succeeded

    llm = FakeLLM([LLMError("nope"), LLMError("nope"), LLMError("nope")])
    with pytest.raises(LLMError):
        judge_report(llm, "report", "x/y", "https://github.com/x/y")


def test_judge_model_name_reads_settings() -> None:
    llm = FakeLLM([], settings=Settings(llm_model="fancy-model"))
    assert _judge_model_name(llm) == "fancy-model"
    assert _judge_model_name(object()) == "object"  # fallback: class name


def test_judge_report_sections_lenient() -> None:
    """Malformed sections entries drop silently; overall scores survive."""
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "sections": [
                        "not a dict",
                        {"name": "", "grounding": 5, "correctness": 5},
                        {"name": 42, "grounding": 5, "correctness": 5},
                        {"name": "No scores"},
                        {"name": "Bad range", "grounding": 9, "correctness": 0},
                        {"name": "Good", "grounding": 4.0, "correctness": 3},
                        {"name": "Missing comments", "grounding": 5, "correctness": 5},
                    ],
                    "coverage": 4,
                    "grounding": 5,
                    "correctness": 3,
                    "actionability": 2,
                    "usefulness": 4,
                }
            )
        ]
    )
    scores = judge_report(llm, "report", "x/y", "https://github.com/x/y")
    assert [s["name"] for s in scores["sections"]] == [
        "Good", "Missing comments"]
    assert scores["sections"][0]["grounding"] == 4
    assert scores["sections"][0]["correctness"] == 3
    assert scores["sections"][1]["comments"] == ""
    assert scores["coverage"] == 4  # overall scores not affected
