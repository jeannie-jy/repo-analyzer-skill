"""RepoRef parsing: URL formats, local paths, artifact workdirs."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_analyzer.errors import InputError
from repo_analyzer.models import RepoRef


def test_from_url_plain() -> None:
    ref = RepoRef.from_url("https://github.com/pallets/flask")
    assert ref.owner == "pallets"
    assert ref.repo == "flask"
    assert ref.api_path == "pallets/flask"
    assert ref.ref is None


def test_from_url_with_git_suffix_and_deep_path() -> None:
    ref = RepoRef.from_url("https://github.com/pallets/flask.git/blob/main/src/flask/app.py")
    assert ref.owner == "pallets"
    assert ref.repo == "flask"  # .git suffix and deep paths are stripped


def test_from_url_www_and_http() -> None:
    assert RepoRef.from_url("http://www.github.com/owner/repo").api_path == "owner/repo"


def test_from_url_keeps_original_url_and_ref() -> None:
    raw = "https://github.com/owner/repo"
    ref = RepoRef.from_url(raw, ref="v1.0")
    assert ref.url == raw
    assert ref.ref == "v1.0"


@pytest.mark.parametrize(
    "bad",
    [
        "https://github.com/",  # no owner/repo
        "https://gitlab.com/owner/repo",  # not github
        "not a url",
        "https://github.com/owner/",  # no repo
        "https://example.com/owner/repo",
    ],
)
def test_from_url_rejects_non_github(bad: str) -> None:
    with pytest.raises(InputError, match="Not a GitHub repository URL"):
        RepoRef.from_url(bad)


def test_from_local_path_accepts_existing_dir(tmp_path) -> None:
    ref = RepoRef.from_local_path(str(tmp_path))
    assert ref.owner == "local"
    assert ref.repo == tmp_path.name
    assert ref.local_path == tmp_path.resolve()


def test_from_local_path_rejects_missing_dir(tmp_path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        RepoRef.from_local_path(str(tmp_path / "nope"))


def test_workdir_normalizes_case_and_underscores(tmp_path) -> None:
    ref = RepoRef.from_url("https://github.com/My_Org/My_Repo")
    workdir = ref.workdir(tmp_path)
    assert workdir == tmp_path / "repos" / "my-org" / "my-repo"


def test_workdir_for_local_ref(tmp_path) -> None:
    ref = RepoRef.from_local_path(str(tmp_path))
    safe_name = tmp_path.name.lower().replace("_", "-")  # same normalization
    assert ref.workdir("out") == Path("out") / "repos" / "local" / safe_name
