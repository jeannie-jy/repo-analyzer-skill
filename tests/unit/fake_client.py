"""In-memory fake of GitHubClient for extractor tests — no network, no mocks.

Usage::

    client = FakeClient()
    client.route("repos/pallets/flask", {"stargazers_count": 5})
    client.raise_on("repos/x/y", RepoNotFoundError("nope"))
    client.route_if(lambda p, q: p == "repos/x/commits" and (q or {}).get("since"), [...])

``route()`` matches the exact path; ``route_if()`` takes a matcher so
callers can distinguish requests that share a path but differ in params
(e.g. the two commits calls in git_stats). A routed Exception is raised.
"""

from __future__ import annotations

import base64
import copy
from collections.abc import Callable
from typing import Any

from repo_analyzer.errors import RepoNotFoundError

Matcher = Callable[[str, dict | None], bool]


class FakeClient:
    def __init__(self) -> None:
        self._rules: list[tuple[Matcher, Any, dict[str, str]]] = []
        self.calls: list[tuple[str, dict | None]] = []

    def route(self, path: str, data: Any, *, headers: dict[str, str] | None = None) -> "FakeClient":
        """Serve ``data`` for an exact path match."""
        return self.route_if(lambda p, _q: p == path, data, headers=headers)

    def route_if(
        self,
        matcher: Matcher,
        data: Any,
        *,
        headers: dict[str, str] | None = None,
    ) -> "FakeClient":
        self._rules.append((matcher, data, headers or {}))
        return self

    def raise_on(self, path: str, error: Exception) -> "FakeClient":
        """Raise ``error`` when this exact path is requested."""
        return self.route(path, error)

    def get_json(self, path: str, *, params: dict | None = None) -> Any:
        data, _ = self._match(path, params)
        return data

    def get_json_headers(self, path: str, *, params: dict | None = None) -> tuple[Any, dict[str, str]]:
        return self._match(path, params)

    def _match(self, path: str, params: dict | None) -> tuple[Any, dict[str, str]]:
        self.calls.append((path, copy.deepcopy(params)))
        for matcher, data, headers in self._rules:
            if matcher(path, params):
                if isinstance(data, Exception):
                    raise data
                return copy.deepcopy(data), headers
        # Unrouted path = the resource is absent, which mirrors how the
        # contents API behaves for missing files (404, not network error).
        raise RepoNotFoundError(f"FakeClient: no route for {path}")

    def called_paths(self) -> list[str]:
        return [p for p, _ in self.calls]

    def call_params_for(self, path: str) -> list[dict | None]:
        return [q for p, q in self.calls if p == path]


def contents_response(text: str, path: str = "file") -> dict:
    """Build a contents-API response carrying ``text`` as base64 content."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return {
        "type": "file",
        "encoding": "base64",
        "content": encoded,
        "path": path,
        "size": len(text),
    }
