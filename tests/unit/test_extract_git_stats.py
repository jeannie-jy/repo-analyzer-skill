from repo_analyzer.extract.git_stats import extract_git_stats
from repo_analyzer.models import RepoRef

from .fake_client import FakeClient

REF = RepoRef.from_url("https://github.com/pallets/flask")

COMMITS_HEAD = [
    {"sha": "abc123", "commit": {"committer": {"date": "2026-08-01T12:00:00Z"}}}
]
CONTRIBUTORS = [
    {"login": "alice", "contributions": 120},
    {"login": "bob", "contributions": 80},
    {"login": "carol", "contributions": 40},
    {"login": "dave", "contributions": 20},
    {"login": "eve", "contributions": 10},
]
PULLS_LINK = (
    '<https://api.github.com/repos/pallets/flask/pulls?state=open&page=2>; rel="next", '
    '<https://api.github.com/repos/pallets/flask/pulls?state=open&page=7>; rel="last"'
)


def _is_head(path: str, params: dict | None) -> bool:
    return path == "repos/pallets/flask/commits" and not (params or {}).get("since")


def _is_activity(path: str, params: dict | None) -> bool:
    return path == "repos/pallets/flask/commits" and bool((params or {}).get("since"))


def _client(active_commits: list, pulls_headers: str = "") -> FakeClient:
    return (
        FakeClient()
        .route_if(_is_head, COMMITS_HEAD)
        .route_if(_is_activity, active_commits)
        .route("repos/pallets/flask/contributors", CONTRIBUTORS)
        .route_if(
            lambda p, q: p == "repos/pallets/flask/pulls",
            [],
            headers={"Link": pulls_headers},
        )
    )


def test_git_stats_full() -> None:
    stats = extract_git_stats(_client([{"sha": "x"}] * 5, PULLS_LINK), REF, "main")
    assert stats.last_commit_at == "2026-08-01T12:00:00Z"
    assert stats.commits_last_30d == 5
    assert stats.commits_30d_capped is False
    assert stats.top_contributors[0].login == "alice"
    assert stats.top_contributors[0].contributions == 120
    assert stats.open_pulls == 7


def test_git_stats_caps_activity_at_100() -> None:
    stats = extract_git_stats(_client([{"sha": f"x{i}"} for i in range(100)]), REF, "main")
    assert stats.commits_last_30d == 100
    assert stats.commits_30d_capped is True


def test_git_stats_falls_back_to_page_length_without_link_header() -> None:
    stats = extract_git_stats(_client([], ""), REF, "main")
    assert stats.open_pulls == 0
