from pathlib import Path

from repo_analyzer.errors import RepoNotFoundError
from repo_analyzer.extract.readme import EXCERPT_CHARS, extract_readme
from repo_analyzer.models import RepoRef

from .fake_client import FakeClient, contents_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REF = RepoRef.from_url("https://github.com/pallets/flask")


def test_readme_with_quickstart_commands() -> None:
    text = (FIXTURES / "README_sample.md").read_text(encoding="utf-8")
    client = FakeClient().route(
        "repos/pallets/flask/readme", contents_response(text, "README.md")
    )
    info = extract_readme(client, REF, "main")
    assert info.path == "README.md"
    assert info.excerpt.startswith("# My Project")
    commands = info.quickstart_commands
    assert "pip install myproject" in commands
    assert "flask run" in commands
    assert "docker build -t myproject ." in commands
    assert len(commands) == 3  # list items in plain text are not commands


def test_readme_excerpt_is_truncated() -> None:
    long_text = "# T\n" + ("word\n" * 5000)
    client = FakeClient().route(
        "repos/pallets/flask/readme", contents_response(long_text, "README.md")
    )
    info = extract_readme(client, REF, "main")
    assert len(info.excerpt) == EXCERPT_CHARS


def test_readme_missing_is_not_an_error() -> None:
    client = FakeClient().raise_on(
        "repos/pallets/flask/readme", RepoNotFoundError("no readme")
    )
    info = extract_readme(client, REF, "main")
    assert info.path is None
    assert info.quickstart_commands == []
