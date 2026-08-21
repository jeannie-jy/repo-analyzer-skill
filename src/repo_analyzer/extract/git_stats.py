"""Git activity stats — commits, contributors, open PRs.

Note on issue counts: GitHub's ``open_issues_count`` includes pull
requests. We record the raw value and fetch open PRs separately so
downstream can compute true open issues if it wants to.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..github_client import GitHubClient
from ..models import Contributor, GitStats, RepoRef

_LAST_PAGE_RE = re.compile(r'page=(\d+)>\s*;\s*rel="last"')
_ACTIVITY_WINDOW_DAYS = 30
_MAX_RECENT_COMMITS = 100  # one page; capped deliberately


def extract_git_stats(client: GitHubClient, ref: RepoRef, branch: str) -> GitStats:
    """Collect commit activity, top contributors, and open PR count."""

    # Latest commit (also gives us the head sha for tree resolution).
    commits = client.get_json(
        f"repos/{ref.api_path}/commits",
        params={"per_page": 1, "sha": branch},
    )
    last_commit_at = None
    if commits:
        committer = commits[0].get("commit", {}).get("committer", {})
        last_commit_at = committer.get("date")

    # Commit count in the last 30 days (capped at one page of 100).
    since = (datetime.now(timezone.utc) - timedelta(days=_ACTIVITY_WINDOW_DAYS)).isoformat()
    recent = client.get_json(
        f"repos/{ref.api_path}/commits",
        params={"since": since, "per_page": _MAX_RECENT_COMMITS, "sha": branch},
    )
    commits_30d = len(recent) if isinstance(recent, list) else 0
    capped = commits_30d >= _MAX_RECENT_COMMITS

    # Top contributors.
    contributors = client.get_json(
        f"repos/{ref.api_path}/contributors",
        params={"per_page": 5},
    )
    top = [
        Contributor(login=c.get("login", "?"), contributions=c.get("contributions", 0))
        for c in contributors
        if isinstance(c, dict)
    ]

    # Open pull requests (parse the total from the Link header).
    pulls, headers = client.get_json_headers(
        f"repos/{ref.api_path}/pulls",
        params={"state": "open", "per_page": 1},
    )
    open_pulls = _total_from_link(headers.get("Link", ""))
    if open_pulls is None:
        open_pulls = len(pulls) if isinstance(pulls, list) else None

    return GitStats(
        last_commit_at=last_commit_at,
        commits_last_30d=commits_30d,
        commits_30d_capped=capped,
        top_contributors=top,
        open_pulls=open_pulls,
    )


def _total_from_link(link_header: str) -> int | None:
    match = _LAST_PAGE_RE.search(link_header)
    return int(match.group(1)) if match else None
