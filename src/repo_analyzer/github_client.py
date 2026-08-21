"""Minimal GitHub REST client (stdlib only).

Phase 2 skeleton: the client contract plus the HTTP-status → typed-error
mapping, which the CLI already branches on. The full implementation
(retry/backoff, rate-limit bookkeeping, 404-vs-private distinction) lands
in Phase 3 together with the extract modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import Settings
from .errors import (
    AuthError,
    ForbiddenError,
    GitHubAPIError,
    NetworkError,
    RateLimitError,
    RepoNotFoundError,
)

DEFAULT_TIMEOUT_SECONDS = 30.0


def map_http_error(
    status: int,
    *,
    headers: Mapping[str, str] | None = None,
    body: str = "",
) -> GitHubAPIError:
    """Map an HTTP status to the typed error that describes it.

    Headers and body are inspected where they carry extra signal (e.g.
    ``Retry-After`` on rate limits). This function is pure and unit-tested
    in isolation; ``GitHubClient`` calls it after every response.
    """
    headers = headers or {}
    retry_after = _parse_retry_after(headers.get("Retry-After"))

    if status == 401:
        return AuthError(
            "Authentication failed (HTTP 401). Check GITHUB_TOKEN.",
            status_code=status,
        )
    if status == 403:
        if retry_after is not None or "rate limit" in body.lower():
            return RateLimitError(
                "API rate limit exceeded (HTTP 403).",
                status_code=status,
                retry_after=retry_after,
            )
        return ForbiddenError(
            "Access forbidden (HTTP 403).",
            status_code=status,
        )
    if status == 404:
        return RepoNotFoundError(
            "Repository not found (HTTP 404). It does not exist, or it is "
            "private and the current token lacks access.",
            status_code=status,
        )
    if status == 429:
        return RateLimitError(
            "API rate limit exceeded (HTTP 429).",
            status_code=status,
            retry_after=retry_after,
        )
    return GitHubAPIError(f"GitHub API error (HTTP {status}).", status_code=status)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class GitHubClient:
    """Thin wrapper around the GitHub REST API.

    Attributes:
        settings: runtime settings (token, API URL).
        timeout: per-request timeout in seconds.
        max_retries: retries for transient failures (network, 5xx, rate limit).
    """

    settings: Settings
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = 3

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """GET an API endpoint and return parsed JSON.

        ``path`` is relative to the API root, e.g. ``"repos/pallets/flask"``.
        Raises the typed errors from :mod:`repo_analyzer.errors`.
        """
        raise NotImplementedError(
            "Implemented in Phase 3 (deterministic extraction layer)."
        )
