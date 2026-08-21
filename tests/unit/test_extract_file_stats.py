from repo_analyzer.extract.file_stats import extract_file_stats
from repo_analyzer.models import RepoRef, RepoTree, TreeEntry

from .fake_client import FakeClient

REF = RepoRef.from_url("https://github.com/pallets/flask")


def _noop_raw(_ref, _branch, _path) -> str:
    return "line1\nline2\n"


def test_file_stats_excludes_vendored_and_dirs() -> None:
    tree = RepoTree(
        entries=[
            TreeEntry("src/app.py", "blob", 100),
            TreeEntry("src/util.py", "blob", 200),
            TreeEntry("node_modules/dep/index.js", "blob", 99_999),
            TreeEntry(".github/workflows/ci.yml", "blob", 700),
            TreeEntry("docs", "tree", None),
        ]
    )
    stats = extract_file_stats(
        FakeClient(), REF, "main", tree, fetch_raw_fn=_noop_raw
    )
    assert stats.total_files == 2
    assert stats.total_bytes == 300
    assert stats.files_by_extension == {".py": 2}
    assert stats.line_counts == {"src/app.py": 2, "src/util.py": 2}
    assert all(f.path != "node_modules/dep/index.js" for f in stats.largest_files)


def test_largest_files_are_sorted_top15() -> None:
    tree = RepoTree(
        entries=[TreeEntry(f"f{i}.py", "blob", i * 10) for i in range(1, 30)]
    )
    stats = extract_file_stats(
        FakeClient(), REF, "main", tree, fetch_raw_fn=_noop_raw
    )
    assert len(stats.largest_files) == 15
    assert stats.largest_files[0].path == "f29.py"
    assert stats.largest_files[0].size_bytes == 290
    assert stats.total_files == 29


def test_raw_fetch_failure_is_best_effort() -> None:
    tree = RepoTree(entries=[TreeEntry("src/app.py", "blob", 100)])
    def flaky(_ref, _branch, _path) -> str:
        raise OSError("raw down")
    stats = extract_file_stats(FakeClient(), REF, "main", tree, fetch_raw_fn=flaky)
    assert stats.line_counts == {}
    assert stats.total_files == 1
