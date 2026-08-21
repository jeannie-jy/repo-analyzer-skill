from pathlib import Path

from repo_analyzer.extract.entrypoints import extract_entrypoints
from repo_analyzer.models import RepoRef, RepoTree, TreeEntry

from .fake_client import FakeClient, contents_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REF = RepoRef.from_url("https://github.com/pallets/flask")


def _tree_with(*paths: str) -> RepoTree:
    return RepoTree(entries=[TreeEntry(path=p, type="blob", size=10) for p in paths])


def _candidates_of_kind(candidates, kind: str) -> list:
    return [c for c in candidates if c.kind == kind]


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------


def test_package_json_bin_file_in_tree_gets_strong_confidence() -> None:
    content = (FIXTURES / "manifest_package.json").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/contents/package.json",
        contents_response(content, "package.json"),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("package.json", "bin/express.js"))
    cli = _candidates_of_kind(candidates, "cli")
    assert any(c.path == "bin/express.js" and c.confidence == 0.95 for c in cli)


def test_package_json_bin_missing_from_tree_is_weaker() -> None:
    content = (FIXTURES / "manifest_package.json").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/contents/package.json",
        contents_response(content, "package.json"),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("package.json"))
    cli = _candidates_of_kind(candidates, "cli")
    assert any(
        c.path == "package.json" and c.confidence == 0.85 and "not in tree" in c.heuristic
        for c in cli
    )


def test_package_json_start_script_is_http_server_candidate() -> None:
    content = (FIXTURES / "manifest_package.json").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/contents/package.json",
        contents_response(content, "package.json"),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("package.json"))
    http = _candidates_of_kind(candidates, "http_server")
    assert any(c.invocation == "npm run start" for c in http)
    # test script is a quality gate, not an entry point
    assert all("test" not in (c.heuristic or "") for c in candidates)


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------


def test_pyproject_scripts_produce_cli_candidate() -> None:
    content = (FIXTURES / "manifest_pyproject.toml").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/contents/pyproject.toml",
        contents_response(content, "pyproject.toml"),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("pyproject.toml"))
    cli = _candidates_of_kind(candidates, "cli")
    assert cli and cli[0].confidence == 0.95
    assert "flask" in (cli[0].invocation or "")


# ---------------------------------------------------------------------------
# Dockerfile / Makefile
# ---------------------------------------------------------------------------


def test_dockerfile_cmd_produces_container_candidate() -> None:
    content = (FIXTURES / "manifest_dockerfile").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/contents/Dockerfile",
        contents_response(content, "Dockerfile"),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("Dockerfile"))
    container = _candidates_of_kind(candidates, "container_entry")
    cmd = [c for c in container if "CMD directive" in c.heuristic]
    assert cmd
    assert "flask" in (cmd[0].invocation or "")


def test_makefile_with_dev_targets() -> None:
    client = FakeClient().route(
        "repos/pallets/flask/contents/Makefile",
        contents_response(".PHONY: run test\nrun:\n\ttest -x\n", "Makefile"),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("Makefile"))
    assert any(c.kind == "build_entry" for c in candidates)


# ---------------------------------------------------------------------------
# file-presence rules
# ---------------------------------------------------------------------------


def test_file_presence_rules() -> None:
    client = FakeClient()
    candidates = extract_entrypoints(
        client, REF, "main", _tree_with("manage.py", "__main__.py", "src/main.go")
    )
    kinds = {c.kind for c in candidates}
    assert "cli" in kinds  # manage.py
    assert "library_entry" in kinds  # __main__.py
    assert "entrypoint_script" in kinds  # main.go
    manage = next(c for c in candidates if c.path == "manage.py")
    assert manage.confidence == 0.9


def test_missing_manifest_is_skipped_not_an_error() -> None:
    # No package.json in the tree -> fetch 404s -> no candidates from it.
    candidates = extract_entrypoints(FakeClient(), REF, "main", _tree_with("app.py"))
    assert candidates  # app.py rule still fires
