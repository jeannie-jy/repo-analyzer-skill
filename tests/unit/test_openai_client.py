"""OpenAICompatClient integration tests against a local HTTP server.

Same technique as the GitHubClient suite: ThreadingHTTPServer stands in
for the provider, no network, no mocking library. Covers the wire format
(model/messages/temperature/max_tokens), auth header, retry semantics,
and response parsing.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from repo_analyzer.config import Settings
from repo_analyzer.errors import LLMError
from repo_analyzer.llm.openai_client import OpenAICompatClient

NOT_FOUND = (404, {}, b'{"error": "Not Found"}')


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    force_disconnect: set = set()
    received_headers: list[dict] = []
    received_bodies: list[bytes] = []
    received_paths: list[str] = []

    def do_POST(self) -> None:
        self.__class__.received_headers.append(dict(self.headers))
        self.__class__.received_paths.append(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        self.__class__.received_bodies.append(self.rfile.read(length))
        path = self.path.split("?")[0]
        if path in self.__class__.force_disconnect:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.close_connection = True
            return
        entry = self.routes.get(path, NOT_FOUND)
        if isinstance(entry, list):
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
    _Handler.received_bodies = []
    _Handler.received_paths = []
    _Handler.force_disconnect = set()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _client(server_url: str, *, max_retries: int = 0, sleeps: list[float] | None = None) -> OpenAICompatClient:
    settings = Settings(llm_base_url=f"{server_url}/v1", llm_api_key="sk-test", llm_model="m1")
    return OpenAICompatClient(
        settings,
        max_retries=max_retries,
        sleep_fn=lambda seconds: sleeps.append(seconds) if sleeps is not None else None,
    )


def _reply(text: str) -> tuple[int, dict, bytes]:
    body = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
    return (200, {"Content-Type": "application/json"}, body)


def test_complete_sends_correct_wire_format(server) -> None:
    _Handler.routes = {"/v1/chat/completions": _reply("hello!")}
    client = _client(server)
    messages = [{"role": "user", "content": "hi"}]
    assert client.complete(messages, max_tokens=100) == "hello!"

    assert _Handler.received_paths == ["/v1/chat/completions"]
    sent = {k.lower(): v for k, v in _Handler.received_headers[-1].items()}
    assert sent["authorization"] == "Bearer sk-test"
    assert sent["content-type"] == "application/json"
    body = json.loads(_Handler.received_bodies[-1])
    assert body == {
        "model": "m1",
        "messages": messages,
        "temperature": pytest.approx(0.2),
        "max_tokens": 100,
    }


def test_reasoning_tuning_reaches_the_wire(server) -> None:
    _Handler.routes = {"/v1/chat/completions": _reply("ok")}
    settings = Settings(
        llm_base_url=f"{server}/v1",
        llm_api_key="sk-test",
        llm_model="deepseek-v4-flash",
        llm_max_output_tokens=16384,
        llm_reasoning_effort="low",
    )
    client = OpenAICompatClient(settings)
    client.complete([{"role": "user", "content": "x"}])
    body = json.loads(_Handler.received_bodies[-1])
    assert body["max_tokens"] == 16384
    assert body["reasoning_effort"] == "low"


def test_settings_max_tokens_is_default_when_not_overridden(server) -> None:
    _Handler.routes = {"/v1/chat/completions": _reply("ok")}
    settings = Settings(llm_base_url=f"{server}/v1", llm_api_key="k", llm_model="m")
    OpenAICompatClient(settings).complete([{"role": "user", "content": "x"}])
    body = json.loads(_Handler.received_bodies[-1])
    assert body["max_tokens"] == 4096
    assert "reasoning_effort" not in body


def test_empty_content_from_reasoning_model_is_diagnosed(server) -> None:
    body = json.dumps(
        {
            "choices": [
                {
                    "message": {"content": ""},
                    "finish_reason": "length",
                }
            ],
            "usage": {"completion_tokens": 4096,
                      "completion_tokens_details": {"reasoning_tokens": 4096}},
        }
    ).encode()
    _Handler.routes = {"/v1/chat/completions": (200, {"Content-Type": "application/json"}, body)}
    client = _client(server)
    with pytest.raises(LLMError, match="LLM_MAX_OUTPUT_TOKENS"):
        client.complete([{"role": "user", "content": "x"}])


def test_429_retries_then_succeeds(server) -> None:
    _Handler.routes = {
        "/v1/chat/completions": [
            (429, {"Retry-After": "1"}, b'{"error": "slow down"}'),
            _reply("ok"),
        ]
    }
    sleeps: list[float] = []
    client = _client(server, max_retries=3, sleeps=sleeps)
    assert client.complete([{"role": "user", "content": "x"}]) == "ok"
    assert sleeps == [1.0]


def test_429_exhausts_retries(server) -> None:
    _Handler.routes = {
        "/v1/chat/completions": (429, {}, b'{"error": "rate limited"}')
    }
    sleeps: list[float] = []
    client = _client(server, max_retries=1, sleeps=sleeps)
    with pytest.raises(LLMError, match="429"):
        client.complete([{"role": "user", "content": "x"}])
    assert sleeps == [2.0]  # exponential backoff, no Retry-After


def test_401_raises_without_retry(server) -> None:
    _Handler.routes = {
        "/v1/chat/completions": (401, {}, b'{"error": "bad key"}')
    }
    sleeps: list[float] = []
    client = _client(server, max_retries=3, sleeps=sleeps)
    with pytest.raises(LLMError, match="401"):
        client.complete([{"role": "user", "content": "x"}])
    assert sleeps == []  # auth errors are not transient


def test_500_retries_then_raises(server) -> None:
    _Handler.routes = {
        "/v1/chat/completions": [(500, {}, b"boom"), (500, {}, b"boom")]
    }
    client = _client(server, max_retries=1)
    with pytest.raises(LLMError, match="500"):
        client.complete([{"role": "user", "content": "x"}])


def test_network_error_retries_then_raises(server) -> None:
    _Handler.force_disconnect = {"/v1/chat/completions"}
    sleeps: list[float] = []
    client = _client(server, max_retries=2, sleeps=sleeps)
    with pytest.raises(LLMError, match="Network error"):
        client.complete([{"role": "user", "content": "x"}])
    assert len(sleeps) == 2


def test_non_json_response_raises(server) -> None:
    _Handler.routes = {"/v1/chat/completions": (200, {}, b"<html>not json</html>")}
    with pytest.raises(LLMError, match="non-JSON"):
        _client(server).complete([{"role": "user", "content": "x"}])


def test_response_without_choices_raises(server) -> None:
    _Handler.routes = {
        "/v1/chat/completions": (200, {}, b'{"foo": "bar"}')
    }
    with pytest.raises(LLMError, match="missing choices"):
        _client(server).complete([{"role": "user", "content": "x"}])
