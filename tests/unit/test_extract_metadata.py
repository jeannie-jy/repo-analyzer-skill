import json
from pathlib import Path

from repo_analyzer.extract.metadata import extract_metadata
from repo_analyzer.models import RepoRef

from .fake_client import FakeClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REF = RepoRef.from_url("https://github.com/pallets/flask")


def _repo_api() -> dict:
    return json.loads((FIXTURES / "repo_api.json").read_text(encoding="utf-8"))


def test_extract_metadata_maps_all_fields() -> None:
    client = FakeClient().route("repos/pallets/flask", _repo_api())
    meta = extract_metadata(client, REF)
    assert meta.description.startswith("The Python micro framework")
    assert meta.stars == 71123
    assert meta.forks == 16789
    assert meta.watchers == 71123
    assert meta.license_name == "BSD-3-Clause"
    assert meta.topics == ["web", "python", "framework", "wsgi"]
    assert meta.default_branch == "main"
    assert meta.is_archived is False
    assert meta.is_fork is False
    assert meta.open_issues_count == 40
    assert meta.created_at == "2010-04-06T14:08:37Z"


def test_extract_metadata_tolerates_missing_fields() -> None:
    client = FakeClient().route("repos/pallets/flask", {"default_branch": "main"})
    meta = extract_metadata(client, REF)
    assert meta.stars == 0
    assert meta.topics == []
    assert meta.license_name is None
    assert meta.default_branch == "main"
