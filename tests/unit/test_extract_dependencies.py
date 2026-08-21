import json
from pathlib import Path

from repo_analyzer.extract.dependencies import detect_manifests, extract_dependencies
from repo_analyzer.models import RepoRef, RepoTree, TreeEntry

from .fake_client import FakeClient, contents_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REF = RepoRef.from_url("https://github.com/pallets/flask")


def _tree_with(*paths: str) -> RepoTree:
    return RepoTree(entries=[TreeEntry(path=p, type="blob", size=10) for p in paths])


def _client_for(contents: dict[str, str]) -> FakeClient:
    client = FakeClient()
    for path, text in contents.items():
        client.route(
            f"repos/pallets/flask/contents/{path}", contents_response(text, path)
        )
    return client


# ---------------------------------------------------------------------------
# manifest detection
# ---------------------------------------------------------------------------


def test_detect_manifests() -> None:
    tree = _tree_with(
        "package.json", "src/requirements.txt", "go.mod", "pubspec.yaml", "Makefile"
    )
    kinds = {m.path: m.kind for m in detect_manifests(tree)}
    assert kinds == {
        "package.json": "npm",
        "src/requirements.txt": "pip",
        "go.mod": "go",
        "pubspec.yaml": "dart",
    }


def test_detect_manifests_caps_at_max() -> None:
    tree = _tree_with(*(f"pkg{i}/package.json" for i in range(30)))
    assert len(detect_manifests(tree)) == 20


# ---------------------------------------------------------------------------
# per-format parsers through the full extract_dependencies path
# ---------------------------------------------------------------------------


def test_extract_pyproject_dependencies() -> None:
    content = (FIXTURES / "manifest_pyproject.toml").read_text(encoding="utf-8")
    deps = extract_dependencies(
        _client_for({"pyproject.toml": content}), REF, "main", _tree_with("pyproject.toml")
    )
    names = {(d.name, d.category) for d in deps.direct}
    assert ("Werkzeug", "runtime") in names
    assert ("click", "runtime") in names
    assert ("pytest", "dev") in names
    assert deps.unparseable == []


def test_extract_package_json_categories() -> None:
    content = (FIXTURES / "manifest_package.json").read_text(encoding="utf-8")
    deps = extract_dependencies(
        _client_for({"package.json": content}), REF, "main", _tree_with("package.json")
    )
    by_name = {d.name: d.category for d in deps.direct}
    assert by_name["body-parser"] == "runtime"
    assert by_name["jest"] == "dev"
    assert by_name["react"] == "runtime"  # peerDependencies


def test_extract_go_mod() -> None:
    content = (FIXTURES / "manifest_go.mod").read_text(encoding="utf-8")
    deps = extract_dependencies(
        _client_for({"go.mod": content}), REF, "main", _tree_with("go.mod")
    )
    versions = {d.name: d.version for d in deps.direct}
    assert versions["github.com/spf13/cobra"] == "v1.8.0"
    assert versions["github.com/google/uuid"] == "v1.6.0"  # single-line require
    assert len(deps.direct) == 3


def test_extract_requirements_txt() -> None:
    content = (FIXTURES / "manifest_requirements.txt").read_text(encoding="utf-8")
    deps = extract_dependencies(
        _client_for({"requirements.txt": content}), REF, "main", _tree_with("requirements.txt")
    )
    names = [d.name for d in deps.direct]
    assert names == ["Werkzeug", "Jinja2", "click"]  # -r / -e / comments skipped
    assert deps.direct[0].version == ">=3.1"
    assert deps.direct[2].version is None


def test_extract_pubspec_yaml() -> None:
    yaml_content = """
name: my_app
environment:
  sdk: ">=3.0.0"
dependencies:
  flutter:
    sdk: flutter
  http: ^1.1.0
  provider: 6.0.5
dev_dependencies:
  flutter_test:
    sdk: flutter
"""
    deps = extract_dependencies(
        _client_for({"pubspec.yaml": yaml_content}),
        REF,
        "main",
        _tree_with("pubspec.yaml"),
    )
    by_name = {d.name: d.version for d in deps.direct}
    assert by_name.get("http") == "^1.1.0"
    assert by_name.get("provider") == "6.0.5"
    assert "flutter" not in by_name
    assert "sdk" not in by_name


def test_unparseable_manifest_is_recorded_not_fatal() -> None:
    client = FakeClient().route(
        "repos/pallets/flask/contents/package.json",
        contents_response("{not valid json", "package.json"),
    )
    deps = extract_dependencies(client, REF, "main", _tree_with("package.json"))
    assert deps.direct == []
    assert len(deps.unparseable) == 1
    assert deps.unparseable[0].path == "package.json"
    assert deps.unparseable[0].reason  # a real reason, whatever json says


def test_missing_manifest_is_recorded_as_unparseable() -> None:
    deps = extract_dependencies(
        FakeClient(), REF, "main", _tree_with("package.json")
    )  # no contents route -> 404 -> None
    assert len(deps.unparseable) == 1
    assert "missing" in deps.unparseable[0].reason


def test_serializes_to_json_roundtrip() -> None:
    content = (FIXTURES / "manifest_pyproject.toml").read_text(encoding="utf-8")
    deps = extract_dependencies(
        _client_for({"pyproject.toml": content}), REF, "main", _tree_with("pyproject.toml")
    )
    as_json = json.loads(json.dumps([d.__dict__ for d in deps.direct]))
    assert as_json[0]["name"] == "Werkzeug"
