"""OpenAI-compatible chat client (stdlib only).

Speaks the ``/chat/completions`` wire format, so any provider that mirrors
it works unchanged: OpenAI, DeepSeek, Moonshot/Kimi, Qwen, local
vLLM/Ollama gateways, etc. Endpoint, key, and model all come from
:class:`Settings` - nothing is hard-coded.

Retry semantics mirror :class:`GitHubClient`: exponential backoff for
transient failures (429 / 5xx), honoring ``Retry-After``, plus the same
injectable ``sleep_fn`` so tests never wait.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..errors import LLMError
from ..github_client import _backoff_seconds
from .base import DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_TEMPERATURE, LLMMessage

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 3
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class OpenAICompatClient:
    """Chat-completions client for OpenAI-compatible endpoints."""

    settings: Settings
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    sleep_fn: Callable[[float], None] = time.sleep

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> str:
        """Complete a chat conversation and return the reply text.

        Raises :class:`LLMError` for auth/forbidden (no retry), malformed
        responses, or transient failures that exhausted the retries.
        """
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": self.settings.llm_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")

        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(
                    self._request(url, body), timeout=self.timeout
                ) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return _extract_text(data)
            except urllib.error.HTTPError as exc:
                status = exc.code
                body_text = exc.read().decode("utf-8", errors="replace")
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
                if status in _TRANSIENT_STATUSES and attempt < self.max_retries:
                    attempt += 1
                    self.sleep_fn(_backoff_seconds(attempt, retry_after))
                    continue
                raise LLMError(
                    _describe_http_error(status, body_text)
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    self.sleep_fn(_backoff_seconds(attempt))
                    continue
                raise LLMError(f"Network error calling LLM provider: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise LLMError(
                    "LLM provider returned a non-JSON response."
                ) from exc

    # -- internals ----------------------------------------------------------

    def _request(self, url: str, body: bytes) -> urllib.request.Request:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return urllib.request.Request(url, data=body, headers=headers, method="POST")


def _extract_text(data: Mapping[str, Any]) -> str:
    """Pull ``choices[0].message.content`` out of a chat response."""
    try:
        choices = data["choices"]
        text = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "LLM provider response is missing choices[0].message.content."
        ) from exc
    if not isinstance(text, str):
        raise LLMError("LLM provider returned a non-string message content.")
    return text


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _describe_http_error(status: int, body: str) -> str:
    hint = ""
    snippet = body.strip()[:200]
    if status == 401:
        hint = " (check the API key in LLM_API_KEY)"
    elif status == 403:
        hint = " (forbidden - check key permissions / endpoint)"
    elif status == 404:
        hint = " (check LLM_BASE_URL - is the endpoint /chat/completions valid?)"
    elif status == 429:
        hint = " (rate limit; retries exhausted)"
    elif status >= 500:
        hint = " (provider error; retries exhausted)"
    return f"LLM provider returned HTTP {status}{hint}: {snippet or '(empty body)'}"
