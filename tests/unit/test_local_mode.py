"""Local-directory mode: snapshots, per-module local branches, the full
local pipeline, and CLI resolution. Git-backed tests skip when git is
not installed (``pytest`` on a machine without git still passes)."""

from __future__ import annotations

import json
import subprocess

import pytest

from repo_analyzer.config import Settings
from repo_analyzer.errors import InputError
from repo_analyzer.extract.local import (
    default_branch_local,
    git_snapshot,
    is_git_repo,
    read_text_local,
    walk_snapshot,
)
from repo_analyzer.extract.metadata import extract_metadata
from repo_analyzer.extract.readme import extract_readme
from repo_analyzer.github_client import GitHubClient, fetch_file_content
from repo_analyzer.models import RepoRef
from repo_analyzer.pipeline.facts import extract_facts

EMPTY_ENV = {"PATH": "/bin"}


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


requires_git = pytest.mark.skipif(not _git_available(), reason="git not installed")


def _git_init(repo: Path, *files: tuple[str, str]) -> None:
    """git init + add + commit; the first commit needs a fake identity."""
    subprocess.run(["git", "init", "-b", "main", str(repo)],
                   capture_output=True, check=True)
    for rel, content in files:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@t",
         "commit", "-m", "init"],
        capture_output=True, check=True,
    )


def _local_ref(path: Path) -> RepoRef:
    return RepoRef.from_local_path(str(path))


def _client() -> GitHubClient:
    return GitHubClient(Settings.from_env(EMPTY_ENV))


# --- snapshots --------------------------------------------------------------


def test_walk_snapshot_prunes_hidden_and_vendored(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "m.pyc").write_bytes(b"x")
    (tmp_path / ".hidden").write_text("y", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    entries = walk_snapshot(tmp_path)
    paths = {e.path for e in entries}
    assert "src/main.py" in paths
    assert ".venv" not in paths and "node_modules" not in paths
    assert ".hidden" not in paths
    assert all("/" not in p or not p.startswith((".", "src/__pycache__")) for p in paths)
    assert all(e.type == "blob" for e in entries)


def test_walk_snapshot_is_deterministic(tmp_path) -> None:
    for i in range(20):
        (tmp_path / f"f{i:02d}.py").write_text("x" * i, encoding="utf-8")
    first = [e.path for e in walk_snapshot(tmp_path)]
    second = [e.path for e in walk_snapshot(tmp_path)]
    assert first == second


@requires_git
def test_git_snapshot_contains_only_tracked_files(tmp_path) -> None:
    _git_init(tmp_path, ("src/app.py", "print(1)"), ("README.md", "# hi"))
    (tmp_path / "untracked.py").write_text("print(2)", encoding="utf-8")
    entries = git_snapshot(tmp_path)
    assert entries is not None
    paths = {e.path for e in entries}
    assert "src/app.py" in paths and "README.md" in paths
    assert "untracked.py" not in paths
    blob = next(e for e in entries if e.path == "src/app.py")
    assert blob.type == "blob" and blob.size == len("print(1)")


@requires_git
def test_git_snapshot_handles_non_ascii_paths(tmp_path) -> None:
    _git_init(tmp_path, ("docs/中文.md", "内容"), ("README.md", "# hi"))
    paths = {e.path for e in git_snapshot(tmp_path) or []}
    assert "docs/中文.md" in paths  # core.quotepath=false: no octal escapes


@requires_git
def test_git_snapshot_skips_symlinks(tmp_path) -> None:
    _git_init(tmp_path, ("target.txt", "hello"), ("README.md", "# hi"))
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
    except OSError:
        pytest.skip("symlinks not permitted on this system")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=T", "-c", "user.email=t@t",
         "commit", "-m", "add link"],
        capture_output=True,
    )
    paths = {e.path for e in git_snapshot(tmp_path) or []}
    assert "link.txt" not in paths  # symlink mode 120000 skipped


@requires_git
def test_git_snapshot_returns_none_for_non_git_dir(tmp_path) -> None:
    assert git_snapshot(tmp_path) is None
    assert is_git_repo(tmp_path) is False


def test_default_branch_local_fallback_without_git(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    assert default_branch_local(tmp_path) == "dev"


def test_default_branch_local_no_git_at_all(tmp_path) -> None:
    assert default_branch_local(tmp_path) == "main"


@requires_git
def test_default_branch_local_from_git(tmp_path) -> None:
    _git_init(tmp_path, ("README.md", "# hi"))
    assert default_branch_local(tmp_path) == "main"


def test_read_text_local_reads_and_caps(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    assert read_text_local(tmp_path, "a.txt") == "hello"
    assert read_text_local(tmp_path, "missing.txt") is None
    assert read_text_local(tmp_path, "a.txt", max_bytes=3) is None


def test_read_text_local_rejects_escaping_paths(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    assert read_text_local(tmp_path, f"../{outside.name}") is None


# --- per-module local branches ----------------------------------------------


def test_metadata_local_keeps_honest_defaults(tmp_path) -> None:
    meta = extract_metadata(_client(), _local_ref(tmp_path))
    assert meta.default_branch == "main"
    assert meta.stars == 0 and meta.forks == 0 and meta.open_issues_count == 0
    assert meta.description is None


def test_tree_local_walk_mode(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hi", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    tree = extract_tree_local(tmp_path)
    paths = {e.path for e in tree.entries}
    assert "src/main.py" in paths and "README.md" in paths
    assert "src" in paths  # derived directory node
    assert ".venv" not in paths
    assert tree.top_level_dirs == ["src"]
    assert tree.top_level_files == ["README.md"]
    assert tree.truncated is False


def test_tree_local_truncation(tmp_path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
    tree = extract_tree_local(tmp_path, max_entries=5)
    assert tree.truncated is True
    assert len(tree.entries) == 5


def test_languages_local_extension_approximation(tmp_path) -> None:
    (tmp_path / "a.py").write_text("x" * 10, encoding="utf-8")
    (tmp_path / "b.py").write_text("x" * 20, encoding="utf-8")
    (tmp_path / "note.md").write_text("x" * 10, encoding="utf-8")
    (tmp_path / "logo.svg").write_bytes(b"x" * 100)  # unmapped binary: skipped
    langs = extract_languages_local(tmp_path)
    by_name = {l.name: l.bytes for l in langs.languages}
    assert by_name.get("Python") == 30
    assert by_name.get("Markdown") == 10
    assert "logo.svg" not in [l.name for l in langs.languages]
    total = sum(l.percentage for l in langs.languages)
    assert total == pytest.approx(100.0)


def test_readme_local_reads_markdown(tmp_path) -> None:
    (tmp_path / "README.md").write_text(
        "# Proj\n\n```bash\npip install x\n```", encoding="utf-8"
    )
    info = extract_readme(_client(), _local_ref(tmp_path), "main")
    assert info.path == "README.md"
    assert "Proj" in info.excerpt
    assert info.quickstart_commands == ["pip install x"]


def test_readme_local_case_insensitive_and_prefers_md(tmp_path) -> None:
    (tmp_path / "readme.markdown").write_text("old", encoding="utf-8")
    info = extract_readme(_client(), _local_ref(tmp_path), "main")
    assert info.path == "readme.markdown"
    (tmp_path / "README.md").write_text("new", encoding="utf-8")
    info = extract_readme(_client(), _local_ref(tmp_path), "main")
    assert info.path == "README.md"


def test_readme_local_missing_is_empty(tmp_path) -> None:
    info = extract_readme(_client(), _local_ref(tmp_path), "main")
    assert info.path is None and info.excerpt == ""


def test_fetch_file_content_local(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    ref = _local_ref(tmp_path)
    content = fetch_file_content(_client(), ref, "main", "pyproject.toml")
    assert content is not None and "name = 'x'" in content
    assert fetch_file_content(_client(), ref, "main", "missing.toml") is None


@requires_git
def test_git_stats_local_from_real_repo(tmp_path) -> None:
    _git_init(tmp_path, ("README.md", "# hi"))
    stats = git_stats_local(tmp_path)
    assert stats.last_commit_at is not None
    assert stats.commits_last_30d == 1
    assert stats.commits_30d_capped is False
    assert len(stats.top_contributors) == 1
    assert stats.open_issues == 0 and stats.open_pulls is None


def test_git_stats_local_degraded_without_git(tmp_path) -> None:
    from repo_analyzer.errors import ExtractionError

    with pytest.raises(ExtractionError):
        git_stats_local(tmp_path)


# --- full pipeline ----------------------------------------------------------


def test_extract_facts_local_full_run(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
    (tmp_path / "src" / "__main__.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['flask>=3']\n[project.scripts]\ndemo = 'demo.app:main'\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n\n```bash\npip install demo\n```", encoding="utf-8")
    (tmp_path / ".venv").mkdir()

    ref = _local_ref(tmp_path)
    out = tmp_path / "out"
    facts = extract_facts(_client(), ref, output_dir=str(out))

    assert facts.repo["owner"] == "local"
    tree_paths = {e.path for e in facts.tree.entries}
    assert "src/app.py" in tree_paths and ".venv" not in tree_paths
    # entrypoint candidates found via local content fetches
    assert any(c.path == "src/__main__.py" for c in facts.entrypoints)
    assert any(c.path == "pyproject.toml" and c.kind == "cli" for c in facts.entrypoints)
    # dependencies parsed from the local pyproject.toml
    assert any(d.name == "flask" for d in facts.dependencies.direct)
    # readme + languages present
    assert facts.readme.path == "README.md"
    assert any(l.name == "Python" for l in facts.languages.languages)
    # local-mode warnings recorded
    assert any("local mode" in w for w in facts.warnings)

    # artifact written under the hashed workdir
    fact_path = ref.workdir(out) / "repo_facts.json"
    assert fact_path.is_file()
    data = json.loads(fact_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"


def test_extract_facts_local_non_git_warns_about_snapshot(tmp_path) -> None:
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    facts = extract_facts(_client(), _local_ref(tmp_path), output_dir=str(tmp_path / "out"))
    assert any("not a git repository" in w for w in facts.warnings)


# --- CLI resolution ---------------------------------------------------------


def test_resolve_ref_accepts_local_path(tmp_path) -> None:
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    from repo_analyzer.cli import _resolve_ref

    ref = _resolve_ref(str(tmp_path))
    assert ref.local_path == tmp_path.resolve()


def test_resolve_ref_keeps_url_behavior() -> None:
    from repo_analyzer.cli import _resolve_ref

    ref = _resolve_ref("https://github.com/pallets/flask", ref="3.0.0")
    assert ref.api_path == "pallets/flask" and ref.ref == "3.0.0"


def test_resolve_ref_garbage_keeps_url_error() -> None:
    from repo_analyzer.cli import _resolve_ref

    with pytest.raises(InputError, match="Not a GitHub repository URL"):
        _resolve_ref("not a url")


def test_resolve_ref_rejects_ref_with_local_path(tmp_path) -> None:
    from repo_analyzer.cli import _resolve_ref

    with pytest.raises(InputError, match="--ref"):
        _resolve_ref(str(tmp_path), ref="main")


def test_cli_extract_local_path_through_real_parser(tmp_path, capsys) -> None:
    from repo_analyzer.cli import main

    (tmp_path / "main.py").write_text("print(1)\n", encoding="utf-8")
    code = main(["extract", str(tmp_path), "-o", str(tmp_path / "out")])
    assert code == 0
    assert "Extracted facts" in capsys.readouterr().out


def test_cli_analyze_local_path_rejects_before_llm(tmp_path, capsys) -> None:
    from repo_analyzer.cli import main

    code = main(["analyze", str(tmp_path), "--ref", "main", "-o", str(tmp_path / "out")])
    assert code == 2
    assert "--ref" in capsys.readouterr().err


# --- local module helpers (kept at the bottom to mirror module usage) -------


def extract_tree_local(path, *, max_entries=200):
    from repo_analyzer.extract.tree import extract_tree

    return extract_tree(_client(), _local_ref(path), "main", max_entries=max_entries)


def extract_languages_local(path):
    from repo_analyzer.extract.languages import extract_languages

    return extract_languages(_client(), _local_ref(path))


def git_stats_local(path):
    from repo_analyzer.extract.git_stats import extract_git_stats

    return extract_git_stats(_client(), _local_ref(path), "main")
