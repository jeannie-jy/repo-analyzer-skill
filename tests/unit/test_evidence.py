"""Deterministic citation checking against the repository tree."""

from __future__ import annotations

from repo_analyzer.models import RepoTree, TreeEntry
from repo_analyzer.pipeline.evidence import _collect_paths, verify_evidence

from .test_analyze_pipeline import VALID_ANALYSIS


def _tree(*paths: str) -> RepoTree:
    return RepoTree(
        entries=[TreeEntry(path=p, type="blob") for p in paths]
    )


def test_verifies_paths_against_tree() -> None:
    tree = _tree(
        "README.md",
        "src/flask/app.py",
        "src/flask/wrappers.py",
        "pyproject.toml",
        "requirements.txt",
        "tests/test_app.py",
    )
    result = verify_evidence(VALID_ANALYSIS, tree)
    # unique citations in VALID_ANALYSIS: README.md, src/flask/app.py,
    # src/flask/wrappers.py, pyproject.toml, requirements.txt, tests/test_app.py
    assert result.total_citations == 6
    assert result.verified == 6
    assert result.unverified == 0
    assert result.unverified_list == []
    assert result.grounding_ratio == 1.0


def test_unverified_paths_are_listed() -> None:
    tree = _tree("README.md", "pyproject.toml")
    result = verify_evidence(VALID_ANALYSIS, tree)
    assert result.verified == 2
    assert result.unverified == 4
    assert result.unverified_list == [
        "requirements.txt",
        "src/flask/app.py",
        "src/flask/wrappers.py",
        "tests/test_app.py",
    ]
    assert result.grounding_ratio == 2 / 6


def test_citations_are_deduplicated() -> None:
    analysis = {
        "key_files": [
            {"path": "a.py", "why": "x", "evidence": ["a.py", "b.py"]},
            {"path": "b.py", "why": "y", "evidence": ["b.py", "a.py"]},
        ]
    }
    result = verify_evidence(analysis, _tree("a.py", "b.py"))
    assert result.total_citations == 2
    assert result.verified == 2


def test_related_files_are_counted_as_paths() -> None:
    analysis = {
        "contribution_opportunities": [
            {"area": "x", "description": "d", "difficulty": "low",
             "related_files": ["tests/test_app.py"],
             "evidence": ["tests/test_app.py", "extra.py"]}
        ]
    }
    result = verify_evidence(analysis, _tree("tests/test_app.py", "extra.py"))
    assert result.total_citations == 2  # both keys collected, deduped
    assert result.verified == 2


def test_empty_analysis() -> None:
    result = verify_evidence({}, _tree("a.py"))
    assert result.total_citations == 0
    assert result.verified == 0
    assert result.grounding_ratio == 0.0


def test_collect_paths_nested() -> None:
    assert _collect_paths({"a": {"evidence": ["x", "y"]}}) == ["x", "y"]
    assert _collect_paths({"a": [{"evidence": ["x"]}, {"related_files": ["z"]}]}) == ["x", "z"]
    # non-string and empty entries are ignored
    assert _collect_paths({"a": {"evidence": ["x", 7, ""]}}) == ["x"]


def test_to_dict() -> None:
    result = verify_evidence(VALID_ANALYSIS, _tree("README.md"))
    data = result.to_dict()
    assert data["total_citations"] == 6
    assert data["unverified"] == 5
    assert isinstance(data["unverified_list"], list)
