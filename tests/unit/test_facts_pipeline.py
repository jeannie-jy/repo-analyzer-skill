"""End-to-end tests of the facts pipeline against a FakeClient."""

import json
from pathlib import Path

import pytest

from repo_analyzer.errors import ExtractionError, NetworkError, RepoNotFoundError
from repo_analyzer.models import FACTS_FILENAME, RepoRef
from repo_analyzer.pipeline.facts import extract_facts

from .fake_client import FakeClient, contents_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REF = RepoRef.from_url("https://github.com/pallets/flask")

COMMITS_HEAD = [
    {"sha": "abc123", "commit": {"committer": {"date": "2026-08-01T12:00:00Z"}}}
]


def _full_client() -> FakeClient:
    repo_api = json.loads((FIXTURES / "repo_api.json").read_text(encoding="utf-8"))
    tree_api = json.loads((FIXTURES / "tree_flask.json").read_text(encoding="utf-8"))
    pyproject = (FIXTURES / "manifest_pyproject.toml").read_text(encoding="utf-8")
    requirements = (FIXTURES / "manifest_requirements.txt").read_text(encoding="utf-8")
    readme_text = (FIXTURES / "README_sample.md").read_text(encoding="utf-8")
    dockerfile = (FIXTURES / "manifest_dockerfile").read_text(encoding="utf-8")
    package_json = '{"scripts": {"start": "node bin/www"}, "dependencies": {"express": "^5.0.0"}}'

    return (
        FakeClient()
        .route("repos/pallets/flask", repo_api)
        .route("repos/pallets/flask/git/trees/main", tree_api)
        .route("repos/pallets/flask/languages", {"Python": 100_000, "HTML": 20_000})
        .route_if(
            lambda p, q: p == "repos/pallets/flask/commits" and not (q or {}).get("since"),
            COMMITS_HEAD,
        )
        .route_if(
            lambda p, q: p == "repos/pallets/flask/commits" and (q or {}).get("since"),
            [{"sha": "x"}] * 3,
        )
        .route(
            "repos/pallets/flask/contributors",
            [{"login": "alice", "contributions": 10}],
        )
        .route_if(
            lambda p, q: p == "repos/pallets/flask/pulls",
            [],
            headers={"Link": ""},
        )
        .route(
            "repos/pallets/flask/contents/pyproject.toml",
            contents_response(pyproject, "pyproject.toml"),
        )
        .route(
            "repos/pallets/flask/contents/requirements.txt",
            contents_response(requirements, "requirements.txt"),
        )
        .route(
            "repos/pallets/flask/contents/package.json",
            contents_response(package_json, "package.json"),
        )
        .route(
            "repos/pallets/flask/contents/Dockerfile",
            contents_response(dockerfile, "Dockerfile"),
        )
        .route(
            "repos/pallets/flask/readme",
            contents_response(readme_text, "README.md"),
        )
    )


def _noop_raw(_ref, _branch, _path) -> str:
    return "line1\nline2\n"


def test_full_pipeline_writes_complete_facts(tmp_path) -> None:
    facts = extract_facts(
        _full_client(), REF, output_dir=tmp_path, fetch_raw_fn=_noop_raw
    )

    # metadata + ref resolution
    assert facts.metadata.stars == 71123
    assert facts.repo["branch"] == "main"
    assert facts.repo["ref_sha"] == "abc123"

    # tree / languages
    assert len(facts.tree.entries) == 20
    assert facts.languages.languages[0].name == "Python"

    # dependencies (pyproject + requirements + package.json, all parsed)
    dep_names = {d.name for d in facts.dependencies.direct}
    assert {"Werkzeug", "Jinja2", "click", "express"} <= dep_names
    assert facts.dependencies.unparseable == []

    # entry points
    assert any(c.kind == "container_entry" for c in facts.entrypoints)
    assert any(c.kind == "http_server" for c in facts.entrypoints)  # src/flask/app.py
    assert any(c.kind == "http_server" and c.path == "package.json" for c in facts.entrypoints)  # npm start

    # git / files / readme
    assert facts.git.last_commit_at == "2026-08-01T12:00:00Z"
    assert facts.git.commits_last_30d == 3
    assert facts.files.total_files == 11  # 13 blobs minus node_modules + .github
    assert facts.readme.quickstart_commands

    # clean run: no warnings
    assert facts.warnings == []
    assert facts.schema_version == "1.0"

    # artifact on disk is valid JSON with the same content
    written = tmp_path / "repos" / "pallets" / "flask" / FACTS_FILENAME
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["metadata"]["stars"] == 71123
    assert data["repo"]["ref_sha"] == "abc123"


def test_tree_failure_degrades_gracefully(tmp_path) -> None:
    repo_api = json.loads((FIXTURES / "repo_api.json").read_text(encoding="utf-8"))
    client = (
        FakeClient()
        .route("repos/pallets/flask", repo_api)
        .raise_on("repos/pallets/flask/git/trees/main", NetworkError("boom"))
    )
    facts = extract_facts(client, REF, output_dir=tmp_path)
    assert facts.metadata.stars == 71123  # metadata survived
    assert facts.tree.entries == []
    assert any("tree" in w for w in facts.warnings)


def test_metadata_failure_raises(tmp_path) -> None:
    client = FakeClient().raise_on(
        "repos/pallets/flask", RepoNotFoundError("gone")
    )
    with pytest.raises(ExtractionError):
        extract_facts(client, REF, output_dir=tmp_path)
