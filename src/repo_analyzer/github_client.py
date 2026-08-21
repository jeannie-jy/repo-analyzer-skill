"""Minimal GitHub REST client (stdlib only): auth, retries, typed errors.

- ``Accept`` / ``X-GitHub-Api-Version`` headers pinned
- Bearer token from :class:`Settings` when present
- Exponential backoff for transient failures (429 / 5xx / rate-limit 403),
  honoring ``Retry-After`` when the API provides it
- HTTP status mapped to typed errors via :func:`map_http_error`
- ``sleep_fn`` is injectable so tests never wait for real backoff
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import __version__
from .config import Settings
from .models import TOOL_NAME, RepoRef
from .errors import (
    AuthError,
    ForbiddenError,
    GitHubAPIError,
    NetworkError,
    RateLimitError,
    RepoNotFoundError,
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


def map_http_error(
    status: int,
    *,
    headers: Mapping[str, str] | None = None,
    body: str = "",
) -> GitHubAPIError:
    """Map an HTTP status to the typed error that describes it.

    Headers and body are inspected where they carry extra signal (e.g.
    ``Retry-After`` on rate limits). Pure function, unit-tested in
    isolation; ``GitHubClient`` calls it after every response.
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
        return ForbiddenError("Access forbidden (HTTP 403).", status_code=status)
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


def _backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with a ``Retry-After`` override, capped at 60s."""
    if retry_after is not None:
        return min(max(retry_after, 0.0), 60.0)
    return min(2.0**attempt, 30.0)


@dataclass(frozen=True)
class GitHubClient:
    """Thin wrapper around the GitHub REST API.

    Attributes:
        settings: runtime settings (token, API URL).
        timeout: per-request timeout in seconds.
        max_retries: retries for transient failures; 0 disables retrying.
        sleep_fn: used for backoff waits (inject a no-op in tests).
    """

    settings: Settings
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    sleep_fn: Callable[[float], None] = time.sleep

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """GET an API endpoint and return parsed JSON (headers discarded)."""
        data, _ = self.get_json_headers(path, params=params)
        return data

    def get_json_headers(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        """GET an API endpoint, returning ``(json, response_headers)``.

        ``path`` is relative to the API root, e.g. ``"repos/pallets/flask"``.
        Raises the typed errors from :mod:`repo_analyzer.errors`.
        """
        url = self._build_url(path, params)
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(
                    self._request(url), timeout=self.timeout
                ) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    headers = {k: v for k, v in resp.headers.items()}
                    return payload, headers
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                headers = {k: v for k, v in exc.headers.items()}
                error = map_http_error(exc.code, headers=headers, body=body)
                transient = exc.code in _TRANSIENT_STATUSES or isinstance(
                    error, RateLimitError
                )
                if transient and attempt < self.max_retries:
                    attempt += 1
                    self.sleep_fn(
                        _backoff_seconds(attempt, getattr(error, "retry_after", None))
                    )
                    continue
                raise error
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    self.sleep_fn(_backoff_seconds(attempt))
                    continue
                raise NetworkError(
                    f"Network error while calling {path}: {exc}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise GitHubAPIError(
                    f"Invalid JSON response from {path}."
                ) from exc

    # -- internals ----------------------------------------------------------

    def _build_url(self, path: str, params: Mapping[str, Any] | None) -> str:
        base = f"{self.settings.github_api_url.rstrip('/')}/{path.lstrip('/')}"
        if params:
            base += "?" + urllib.parse.urlencode(params)
        return base

    def _request(self, url: str) -> urllib.request.Request:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{TOOL_NAME}/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return urllib.request.Request(url, headers=headers)


# ---------------------------------------------------------------------------
# Content fetching shared by several extract modules
# ---------------------------------------------------------------------------


def fetch_file_content(client: GitHubClient, ref: RepoRef, branch: str, path: str) -> str | None:
    """Fetch a file's decoded text content via the contents API.

    Returns ``None`` when the file is missing, too large for the API, or
    not decodable — callers treat ``None`` as "no information", never as
    an error.
    """
    quoted = urllib.parse.quote(path, safe="/")
    try:
        data = client.get_json(
            f"repos/{ref.api_path}/contents/{quoted}", params={"ref": branch}
        )
    except RepoNotFoundError:
        return None
    if isinstance(data, list) or not data.get("content"):
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return None
