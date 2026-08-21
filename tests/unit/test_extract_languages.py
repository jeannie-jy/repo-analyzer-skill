from repo_analyzer.extract.languages import extract_languages
from repo_analyzer.models import RepoRef

from .fake_client import FakeClient

REF = RepoRef.from_url("https://github.com/pallets/flask")


def test_extract_languages_percentages() -> None:
    client = FakeClient().route(
        "repos/pallets/flask/languages",
        {"Python": 80000, "HTML": 15000, "CSS": 5000},
    )
    stats = extract_languages(client, REF)
    assert stats.total_bytes == 100_000
    assert [l.name for l in stats.languages] == ["Python", "HTML", "CSS"]
    assert stats.languages[0].percentage == 80.0
    assert stats.languages[1].percentage == 15.0
    assert stats.languages[2].percentage == 5.0


def test_extract_languages_empty_repo() -> None:
    client = FakeClient().route("repos/pallets/flask/languages", {})
    assert extract_languages(client, REF).languages == []
