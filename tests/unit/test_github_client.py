"""GitHubClient integration tests against a local HTTP server.

No mocking library and no network — ``ThreadingHTTPServer`` stands in for
api.github.com, including retries, backoff (injected no-op sleep), auth
headers, and query params.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from repo_analyzer.config import Settings
from repo_analyzer.errors import NetworkError, RateLimitError, RepoNotFoundError
from repo_analyzer.github_client import GitHubClient

NOT_FOUND = (404, {}, b'{"message": "Not Found"}')


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    force_disconnect: set = set()
    received_headers: list[dict] = []
    received_paths: list[str] = []

    def do_GET(self) -> None:
        self.__class__.received_headers.append(dict(self.headers))
        self.__class__.received_paths.append(self.path)
        path = self.path.split("?")[0]
        if path in self.__class__.force_disconnect:
            # Simulate a connection-level failure (server drops the socket).
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.close_connection = True
            return
        entry = self.routes.get(path, NOT_FOUND)
        if isinstance(entry, list):  # scripted sequence of responses
            status, headers, body = entry.pop(0) if entry else NOT_FOUND
        else:
            status, headers, body = entry
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():
    _Handler.received_headers = []
    _Handler.received_paths = []
    _Handler.force_disconnect = set()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _client(api_url: str, *, token: str | None = None, max_retries: int = 0, sleeps: list[float] | None = None) -> GitHubClient:
    settings = Settings(github_api_url=api_url, github_token=token)
    return GitHubClient(
        settings,
        max_retries=max_retries,
        sleep_fn=lambda seconds: sleeps.append(seconds) if sleeps is not None else None,
    )


def test_get_json_parses_and_sends_headers(server) -> None:
    _Handler.routes = {"/repos/x/y": (200, {}, b'{"stars": 5}')}
    client = _client(server, token="t0ken")
    assert client.get_json("repos/x/y") == {"stars": 5}
    sent = {k.lower(): v for k, v in _Handler.received_headers[-1].items()}
    assert sent["authorization"] == "Bearer t0ken"
    assert sent["accept"] == "application/vnd.github+json"
    assert sent["x-github-api-version"] == "2022-11-28"


def test_get_json_sends_query_params(server) -> None:
    _Handler.routes = {"/repos/x/y": (200, {}, b"[]")}
    client = _client(server)
    client.get_json("repos/x/y", params={"per_page": 1, "sha": "main"})
    assert _Handler.received_paths[-1].endswith("?per_page=1&sha=main")


def test_404_raises_repo_not_found(server) -> None:
    _Handler.routes = {}
    with pytest.raises(RepoNotFoundError):
        _client(server).get_json("repos/x/y")


def test_429_retries_then_succeeds_honoring_retry_after(server) -> None:
    _Handler.routes = {
        "/repos/x/y": [
            (429, {"Retry-After": "1"}, b"{}"),
            (200, {}, b'{"ok": true}'),
        ]
    }
    sleeps: list[float] = []
    client = _client(server, max_retries=3, sleeps=sleeps)
    assert client.get_json("repos/x/y") == {"ok": True}
    assert sleeps == [1.0]


def test_429_exhausts_retries(server) -> None:
    _Handler.routes = {"/repos/x/y": (429, {"Retry-After": "2"}, b"{}")}
    sleeps: list[float] = []
    client = _client(server, max_retries=1, sleeps=sleeps)
    with pytest.raises(RateLimitError):
        client.get_json("repos/x/y")
    assert len(sleeps) == 1
    assert sleeps[0] == 2.0


def test_500_retries_then_succeeds(server) -> None:
    _Handler.routes = {
        "/repos/x/y": [(500, {}, b"{}"), (200, {}, b'{"ok": true}')]
    }
    client = _client(server, max_retries=2)
    assert client.get_json("repos/x/y") == {"ok": True}


def test_403_rate_limit_body_retries(server) -> None:
    _Handler.routes = {
        "/repos/x/y": [
            (403, {}, b'{"message": "API rate limit exceeded"}'),
            (200, {}, b'{"ok": true}'),
        ]
    }
    client = _client(server, max_retries=2)
    assert client.get_json("repos/x/y") == {"ok": True}


def test_network_error_retries_then_raises(server) -> None:
    # The server accepts the TCP connection and drops it mid-request —
    # deterministic on every platform (no dead-port SYN hangs).
    _Handler.force_disconnect = {"/repos/x/y"}
    sleeps: list[float] = []
    client = _client(server, max_retries=2, sleeps=sleeps)
    with pytest.raises(NetworkError):
        client.get_json("repos/x/y")
    assert len(sleeps) == 2  # exponential backoff, no Retry-After available
