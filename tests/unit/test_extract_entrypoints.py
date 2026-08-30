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
# Cargo.toml ([[bin]] + default bin/lib conventions)
# ---------------------------------------------------------------------------


def test_cargo_bin_target_in_tree() -> None:
    content = (
        '[package]\nname = "fd-find"\n'
        '[[bin]]\nname = "fd"\npath = "src/main.rs"\n'
    )
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response(content, "Cargo.toml"),
    )
    candidates = extract_entrypoints(
        client, REF, "main", _tree_with("Cargo.toml", "src/main.rs")
    )
    cli = _candidates_of_kind(candidates, "cli")
    fd = [c for c in cli if "fd" in (c.invocation or "")]
    assert len(fd) == 1
    assert fd[0].path == "src/main.rs"
    assert fd[0].confidence == 0.95
    assert fd[0].invocation == "cargo run --bin fd"
    assert "Cargo [[bin]] 'fd'" in (fd[0].heuristic or "")


def test_cargo_bin_path_missing_from_tree_is_weaker() -> None:
    content = '[[bin]]\nname = "fd"\npath = "src/main.rs"\n'
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response(content, "Cargo.toml"),
    )
    candidates = extract_entrypoints(
        client, REF, "main", _tree_with("Cargo.toml")
    )
    cli = _candidates_of_kind(candidates, "cli")
    assert any(c.path == "Cargo.toml" and c.confidence == 0.85 for c in cli)


def test_cargo_default_bin_convention() -> None:
    # No [[bin]] table: Cargo still treats src/main.rs as the bin.
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response('[package]\nname = "fd-find"\n', "Cargo.toml"),
    )
    candidates = extract_entrypoints(
        client, REF, "main", _tree_with("Cargo.toml", "src/main.rs")
    )
    cli = _candidates_of_kind(candidates, "cli")
    assert any(
        c.path == "src/main.rs"
        and c.confidence == 0.90
        and "default bin" in (c.heuristic or "")
        for c in cli
    )


def test_cargo_workspace_member_bin_detected() -> None:
    content = '[[bin]]\nname = "member-bin"\npath = "src/main.rs"\n'
    client = FakeClient().route(
        "repos/pallets/flask/contents/crates/member/Cargo.toml",
        contents_response(content, "Cargo.toml"),
    )
    tree = _tree_with(
        "Cargo.toml",
        "crates/member/Cargo.toml",
        "crates/member/src/main.rs",
    )
    candidates = extract_entrypoints(client, REF, "main", tree)
    cli = _candidates_of_kind(candidates, "cli")
    assert any(
        c.path == "crates/member/src/main.rs"
        and c.invocation == "cargo run --bin member-bin"
        for c in cli
    )


def test_cargo_default_lib_target() -> None:
    content = '[package]\nname = "serde-utils"\n'
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response(content, "Cargo.toml"),
    )
    candidates = extract_entrypoints(
        client, REF, "main", _tree_with("Cargo.toml", "src/lib.rs")
    )
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/lib.rs"
    assert lib[0].confidence == 0.70
    assert lib[0].invocation == "use serde-utils"


def test_cargo_explicit_lib_path() -> None:
    content = '[lib]\nname = "core"\npath = "src/engine/lib.rs"\n'
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response(content, "Cargo.toml"),
    )
    candidates = extract_entrypoints(
        client, REF, "main", _tree_with("Cargo.toml", "src/engine/lib.rs")
    )
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/engine/lib.rs"
    assert "Cargo [lib] path" in (lib[0].heuristic or "")


def test_cargo_lib_suppressed_when_bin_exists() -> None:
    # A crate with both bin and lib: the lib is the bin's internals,
    # not a separate user entry — same gate as the Python library root.
    content = (
        '[package]\nname = "app"\n'
        '[[bin]]\nname = "app"\npath = "src/main.rs"\n'
    )
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response(content, "Cargo.toml"),
    )
    tree = _tree_with("Cargo.toml", "src/main.rs", "src/lib.rs")
    candidates = extract_entrypoints(client, REF, "main", tree)
    assert _candidates_of_kind(candidates, "cli")
    assert not _candidates_of_kind(candidates, "library_api")


def test_cargo_lib_not_suppressed_by_makefile() -> None:
    # Build/CI artifacts must not suppress a library import surface.
    client = FakeClient().route(
        "repos/pallets/flask/contents/Cargo.toml",
        contents_response('[package]\nname = "libcrate"\n', "Cargo.toml"),
    )
    tree = _tree_with("Cargo.toml", "src/lib.rs", "Makefile")
    candidates = extract_entrypoints(client, REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/lib.rs"


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


def test_makefile_phony_completions_not_an_entry() -> None:
    # A .PHONY that names only build artifacts (e.g. `completions`) is a
    # packaging target, not a run/dev entry — must not become a candidate.
    client = FakeClient().route(
        "repos/pallets/flask/contents/Makefile",
        contents_response(
            ".PHONY: completions archive\ncompletions:\n\t./exe --gen-completions\n",
            "Makefile",
        ),
    )
    candidates = extract_entrypoints(client, REF, "main", _tree_with("Makefile"))
    assert not _candidates_of_kind(candidates, "build_entry")


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


# ---------------------------------------------------------------------------
# library package root (import surface): pure libraries with no runnable entry
# ---------------------------------------------------------------------------


def test_library_src_layout_root() -> None:
    tree = _tree_with(
        "src/click/__init__.py", "src/click/core.py", "src/click/decorators.py"
    )
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/click/__init__.py"
    assert lib[0].confidence == 0.40
    assert lib[0].invocation == "import click"


def test_library_pyproject_cli_suppresses_library_candidate() -> None:
    content = (FIXTURES / "manifest_pyproject.toml").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/contents/pyproject.toml",
        contents_response(content, "pyproject.toml"),
    )
    tree = _tree_with("pyproject.toml", "src/flask/__init__.py", "src/flask/app.py")
    candidates = extract_entrypoints(client, REF, "main", tree)
    assert _candidates_of_kind(candidates, "cli")
    assert not _candidates_of_kind(candidates, "library_api")


def test_library_top_level_layout() -> None:
    tree = _tree_with("click/__init__.py", "click/core.py")
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "click/__init__.py"
    assert lib[0].invocation == "import click"


def test_library_excluded_dirs_never_win() -> None:
    tree = _tree_with(
        "src/click/__init__.py",
        "src/click/core.py",
        "tests/__init__.py",
        "tests/test_click.py",
        "examples/__init__.py",
        "examples/basic.py",
    )
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/click/__init__.py"


def test_library_no_init_no_candidate() -> None:
    tree = _tree_with("src/click/core.py", "src/click/decorators.py")
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    assert not _candidates_of_kind(candidates, "library_api")


def test_library_single_file_package_not_a_root() -> None:
    candidates = extract_entrypoints(
        FakeClient(), REF, "main", _tree_with("src/click/__init__.py")
    )
    assert not _candidates_of_kind(candidates, "library_api")


def test_library_main_and_root_coexist() -> None:
    tree = _tree_with(
        "src/click/__main__.py", "src/click/__init__.py", "src/click/core.py"
    )
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    assert _candidates_of_kind(candidates, "library_entry")
    assert _candidates_of_kind(candidates, "library_api")


def test_library_src_layout_wins_over_top_level() -> None:
    # src-layout tier beats a top-level package with more files.
    tree = _tree_with(
        "src/click/__init__.py",
        "src/click/core.py",
        "click/__init__.py",
        "click/core.py",
        "click/decorators.py",
        "click/termui.py",
    )
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/click/__init__.py"


def test_library_largest_package_wins_tiebreak() -> None:
    tree = _tree_with(
        "src/foo/__init__.py",
        "src/foo/a.py",
        "src/bar/__init__.py",
        "src/bar/a.py",
        "src/bar/b.py",
        "src/bar/c.py",
    )
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/bar/__init__.py"
    assert lib[0].invocation == "import bar"


def test_library_nested_init_not_a_root() -> None:
    tree = _tree_with(
        "src/click/__init__.py",
        "src/click/core.py",
        "src/click/termui/__init__.py",
        "src/click/termui/term.py",
    )
    candidates = extract_entrypoints(FakeClient(), REF, "main", tree)
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/click/__init__.py"


def test_library_not_suppressed_by_dockerfile() -> None:
    # The skip guard is cli/http_server only — build/CI artifacts must not
    # suppress a library import surface.
    client = FakeClient().route(
        "repos/pallets/flask/contents/Dockerfile",
        contents_response('CMD ["python", "app.py"]\n', "Dockerfile"),
    )
    tree = _tree_with("Dockerfile", "src/click/__init__.py", "src/click/core.py")
    candidates = extract_entrypoints(client, REF, "main", tree)
    assert _candidates_of_kind(candidates, "container_entry")
    lib = _candidates_of_kind(candidates, "library_api")
    assert len(lib) == 1
    assert lib[0].path == "src/click/__init__.py"
