"""Language statistics — one GET on ``/repos/{owner}/{repo}/languages``."""

from __future__ import annotations

from ..github_client import GitHubClient
from ..models import LanguageShare, LanguageStats, RepoRef


def extract_languages(client: GitHubClient, ref: RepoRef) -> LanguageStats:
    """Fetch byte counts per language and compute percentages.

    ``languages`` API returns ``{name: bytes}`` ordered by bytes
    descending; we keep that order and add a one-decimal percentage.
    """
    data = client.get_json(f"repos/{ref.api_path}/languages")
    if not isinstance(data, dict):
        return LanguageStats()
    total = sum(data.values())
    if total <= 0:
        return LanguageStats()
    shares = [
        LanguageShare(
            name=name,
            bytes=byte_count,
            percentage=round(byte_count / total * 100, 1),
        )
        for name, byte_count in sorted(data.items(), key=lambda kv: -kv[1])
    ]
    return LanguageStats(languages=shares)
