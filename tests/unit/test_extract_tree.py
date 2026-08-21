import json
from pathlib import Path

from repo_analyzer.extract.tree import VENDORED_PREFIXES, extract_tree
from repo_analyzer.models import RepoRef

from .fake_client import FakeClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REF = RepoRef.from_url("https://github.com/pallets/flask")


def _tree_api() -> dict:
    return json.loads((FIXTURES / "tree_flask.json").read_text(encoding="utf-8"))


def test_extract_tree_full() -> None:
    client = FakeClient().route("repos/pallets/flask/git/trees/main", _tree_api())
    tree = extract_tree(client, REF, "main")
    assert tree.truncated is False
    assert len(tree.entries) == 20
    assert tree.top_level_dirs == [
        ".github", "docs", "examples", "node_modules", "src", "tests",
    ]
    assert tree.top_level_files == ["README.md", "package.json", "pyproject.toml", "requirements.txt"]
    app = next(e for e in tree.entries if e.path == "src/flask/app.py")
    assert app.type == "blob"
    assert app.size == 15000
    assert tuple(tree.excluded_prefixes) == VENDORED_PREFIXES


def test_extract_tree_truncated_falls_back_to_contents() -> None:
    root_listing = [
        {"name": "src", "path": "src", "type": "tree", "size": None, "sha": "t"},
        {"name": "README.md", "path": "README.md", "type": "blob", "size": 100, "sha": "b"},
    ]
    src_listing = [
        {"name": "app.py", "path": "src/app.py", "type": "blob", "size": 500, "sha": "b2"}
    ]
    client = (
        FakeClient()
        .route(
            "repos/pallets/flask/git/trees/main",
            {"sha": "x", "truncated": True, "tree": []},
        )
        .route("repos/pallets/flask/contents/", root_listing)
        .route("repos/pallets/flask/contents/src", src_listing)
    )
    tree = extract_tree(client, REF, "main")
    assert tree.truncated is True
    paths = {e.path for e in tree.entries}
    assert {"src", "README.md", "src/app.py"} <= paths


def test_extract_tree_caps_entries() -> None:
    client = FakeClient().route("repos/pallets/flask/git/trees/main", _tree_api())
    tree = extract_tree(client, REF, "main", max_entries=5)
    assert len(tree.entries) == 5
    assert tree.truncated is True
