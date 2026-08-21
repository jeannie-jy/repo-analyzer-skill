"""Budgeted sampling: ordering, budget accounting, degradation."""

from __future__ import annotations

from repo_analyzer.context.code_sampler import sample_code
from repo_analyzer.models import EntrypointCandidate, RepoFacts, RepoRef
from repo_analyzer.pipeline.facts import extract_facts

from .fake_client import FakeClient, contents_response
from .test_facts_pipeline import REF, _full_client, _noop_raw


def _load_facts(tmp_path):
    return extract_facts(_full_client(), REF, output_dir=tmp_path, fetch_raw_fn=_noop_raw)


def _entrypoint_facts(paths: list[str]) -> RepoFacts:
    """Minimal facts where every entry point is fetchable — lets the tests
    exercise budget branches without fixture-shaped content sizes."""
    return RepoFacts(
        repo={"branch": "main"},
        entrypoints=[
            EntrypointCandidate(path=path, kind="cli", heuristic="test", confidence=1.0 - i * 0.1)
            for i, path in enumerate(paths)
        ],
    )


def test_priority_order_is_entrypoints_then_manifests_then_largest(tmp_path) -> None:
    client = _full_client().route(
        "repos/pallets/flask/contents/README.md",
        contents_response("readme content", "README.md"),
    )
    facts = _load_facts(tmp_path)
    sample = sample_code(client, REF, "main", facts, budget=40_000)

    # highest-confidence entry point first (PEP 621 cli 0.95 > Dockerfile 0.8)
    assert sample.files[0].path == "pyproject.toml"
    assert sample.files[0].reason.startswith("entrypoint:")
    # manifests dedupe into the list; largest files follow (README.md is
    # the only largest-file candidate whose contents are routed)
    reasons = [f.reason for f in sample.files]
    assert any(r.startswith("manifest:") for r in reasons)
    assert any(r.startswith("largest file") for r in reasons)
    # pyproject.toml appears exactly once despite matching 3 candidate lists
    assert [f.path for f in sample.files].count("pyproject.toml") == 1


def test_missing_files_are_skipped_not_fatal(tmp_path) -> None:
    facts = _load_facts(tmp_path)
    # src/flask/app.py is an entry-point candidate but has no contents route
    sample = sample_code(_full_client(), REF, "main", facts, budget=40_000)
    assert any(
        s.startswith("src/flask/app.py - fetch failed") for s in sample.skipped
    )
    assert all(f.path != "src/flask/app.py" for f in sample.files)


def test_budget_exhaustion_stops_sampling() -> None:
    # Six files of 160 chars = 40 tokens each, budget 200 (single-file cap
    # 50, so none is capped): five fit exactly, the sixth exceeds the
    # remaining 0 -> "budget exhausted" branch.
    paths = [f"f{i}.txt" for i in range(6)]
    client = FakeClient()
    for path in paths:
        client.route(
            f"repos/x/y/contents/{path}", contents_response("x" * 160, path)
        )
    ref = RepoRef.from_url("https://github.com/x/y")
    facts = _entrypoint_facts(paths)
    sample = sample_code(client, ref, "main", facts, budget=200)

    assert sample.total_token_estimate == 200
    assert [f.path for f in sample.files] == paths[:5]
    assert any("budget exhausted" in s for s in sample.skipped)


def test_oversized_single_file_is_capped() -> None:
    # 4000 chars = ~1000 tokens > 25% of the 3000 budget (750) -> capped.
    big = "x" * 4000
    small = "y" * 120
    client = (
        FakeClient()
        .route("repos/x/y/contents/big.txt", contents_response(big, "big.txt"))
        .route("repos/x/y/contents/small.txt", contents_response(small, "small.txt"))
    )
    ref = RepoRef.from_url("https://github.com/x/y")
    facts = _entrypoint_facts(["big.txt", "small.txt"])
    sample = sample_code(client, ref, "main", facts, budget=3000)

    assert [f.path for f in sample.files] == ["small.txt"]
    assert any("single-file cap" in s for s in sample.skipped)


def test_to_manifest_excludes_contents(tmp_path) -> None:
    facts = _load_facts(tmp_path)
    sample = sample_code(_full_client(), REF, "main", facts, budget=40_000)
    manifest = sample.to_manifest()
    assert manifest["budget"] == 40_000
    assert all("content" not in f for f in manifest["files"])
    assert all(f["token_estimate"] > 0 for f in manifest["files"])


def test_vendored_paths_excluded(tmp_path) -> None:
    from repo_analyzer.context.code_sampler import _is_vendored

    assert _is_vendored("node_modules/dep/index.js")
    assert _is_vendored("vendor/lib/x.c")
    assert not _is_vendored("src/main.py")
