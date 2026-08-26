"""Digest annex: builds verbatim from facts, renders labeled numbers."""

from __future__ import annotations

from repo_analyzer.models import (
    FileSize,
    FileStats,
    RepoFacts,
)
from repo_analyzer.pipeline.facts import extract_facts
from repo_analyzer.report.digest_facts import (
    SECTION_TITLE,
    build_digest_facts,
    render_digest_facts,
)

from .test_facts_pipeline import REF, _full_client, _noop_raw


def test_build_annex_copies_facts_verbatim(tmp_path) -> None:
    facts = extract_facts(
        _full_client(), REF, output_dir=tmp_path, fetch_raw_fn=_noop_raw
    )
    annex = build_digest_facts(facts)
    assert annex["metadata"]["stars"] == 71123
    assert annex["git"]["commits_last_30d"] == 3
    assert annex["git"]["top_contributors"] == [
        {"login": "alice", "contributions": 10}
    ]
    assert annex["files"]["total_files"] == facts.files.total_files > 0
    python = next(l for l in annex["languages"] if l["name"] == "Python")
    assert python["bytes"] == 100_000


def test_build_annex_joins_line_counts_into_largest_files() -> None:
    facts = RepoFacts(
        files=FileStats(
            total_files=3,
            total_bytes=1000,
            largest_files=[
                FileSize("a.py", 500),
                FileSize("b.py", 300),
                FileSize("c.py", 200),
            ],
            line_counts={"a.py": 50},
        )
    )
    annex = build_digest_facts(facts)
    by_path = {e["path"]: e for e in annex["files"]["largest_files"]}
    assert by_path["a.py"]["lines"] == 50
    assert by_path["b.py"]["lines"] is None


def test_build_annex_handles_empty_facts() -> None:
    annex = build_digest_facts(RepoFacts())
    assert annex["metadata"]["stars"] == 0
    assert annex["git"]["commits_last_30d"] is None
    assert annex["files"]["largest_files"] == []
    lines = render_digest_facts(annex)
    assert lines and lines[0].startswith("- metadata: 0 stars")


def test_render_annex_labels_endpoint_fields() -> None:
    annex = {
        "metadata": {"stars": 17633, "forks": 1947, "open_issues_count": 87},
        "languages": [{"name": "Python", "percentage": 100.0, "bytes": 910705}],
        "git": {
            "last_commit_at": "2026-08-20T16:12:10Z",
            "commits_last_30d": 20,
            "commits_30d_capped": False,
            "open_issues": 0,
            "open_pulls": 8,
            "top_contributors": [{"login": "davidism", "contributions": 876}],
        },
        "files": {
            "total_files": 156,
            "total_bytes": 1592535,
            "files_by_extension": {},
            "largest_files": [
                {"path": "src/click/core.py", "size_bytes": 147845, "lines": 3799}
            ],
            "line_counts": {},
        },
    }
    text = "\n".join(render_digest_facts(annex))
    # the two issue counts are labeled by endpoint, never merged
    assert "87 open issues (repo metadata, includes PRs)" in text
    assert "open issues (issues search, excludes PRs): 0" in text
    assert "17,633 stars" in text
    assert "1,592,535 bytes" in text
    # line counts joined into largest files: what makes size claims checkable
    assert "src/click/core.py (147,845 B, 3,799 lines)" in text
    assert "top contributors: davidism (876)" in text


def test_render_annex_marks_capped_commits() -> None:
    annex = {
        "metadata": {},
        "languages": [],
        "git": {
            "last_commit_at": None,
            "commits_last_30d": 100,
            "commits_30d_capped": True,
            "open_issues": 0,
            "open_pulls": 3,
            "top_contributors": [],
        },
        "files": {},
    }
    text = "\n".join(render_digest_facts(annex))
    assert "100 commits (30d) (capped)" in text


def test_section_title_identifies_pipeline_computation() -> None:
    assert SECTION_TITLE == "Verified Facts (pipeline-computed)"
