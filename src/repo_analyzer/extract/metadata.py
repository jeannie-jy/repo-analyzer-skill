"""Repository metadata — one GET on ``/repos/{owner}/{repo}``."""

from __future__ import annotations

from ..github_client import GitHubClient
from ..models import RepoMetadata, RepoRef
from .local import default_branch_local


def extract_metadata(client: GitHubClient, ref: RepoRef) -> RepoMetadata:
    """Fetch repository metadata from the GitHub API.

    Every field is mapped defensively (``.get`` with defaults) so API
    shape drift degrades to a default value instead of a crash.

    Local refs get only the branch name — stars, forks, issues, and the
    rest are not determinable without the API, so they stay at honest
    defaults (0/None) instead of being guessed.
    """
    if ref.local_path is not None:
        return RepoMetadata(default_branch=default_branch_local(ref.local_path))

    data = client.get_json(f"repos/{ref.api_path}")
    license_data = data.get("license") or {}
    return RepoMetadata(
        description=data.get("description"),
        stars=data.get("stargazers_count", 0),
        forks=data.get("forks_count", 0),
        watchers=data.get("watchers_count", 0),
        license_name=license_data.get("name") or license_data.get("spdx_id"),
        topics=list(data.get("topics") or []),
        created_at=data.get("created_at"),
        pushed_at=data.get("pushed_at"),
        homepage=data.get("homepage"),
        is_archived=bool(data.get("archived", False)),
        is_fork=bool(data.get("fork", False)),
        size_kb=data.get("size", 0),
        default_branch=data.get("default_branch", "main"),
        open_issues_count=data.get("open_issues_count", 0),
    )
