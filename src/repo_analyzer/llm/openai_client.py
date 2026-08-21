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
from .base import DEFAULT_TEMPERATURE, LLMMessage

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
        max_tokens: int | None = None,
    ) -> str:
        """Complete a chat conversation and return the reply text.

        ``max_tokens`` defaults to ``settings.llm_max_output_tokens``
        (raise it for reasoning models whose chain of thought shares the
        output budget). When ``settings.llm_reasoning_effort`` is set it
        is sent as ``reasoning_effort``; plain chat providers simply
        ignore it.

        Raises :class:`LLMError` for auth/forbidden (no retry), malformed
        responses, or transient failures that exhausted the retries.
        """
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.settings.llm_max_output_tokens,
        }
        if self.settings.llm_reasoning_effort:
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
        body = json.dumps(payload).encode("utf-8")

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
    """Pull ``choices[0].message.content`` out of a chat response.

    An empty content string from a reasoning model (finish_reason
    "length", reasoning_tokens reported) is the classic symptom of the
    chain of thought consuming the whole output budget — diagnose it
    with the numbers instead of returning a confusing empty prompt.
    """
    try:
        choices = data["choices"]
        choice = choices[0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "LLM provider response is missing choices[0].message.content."
        ) from exc
    if not isinstance(text, str):
        raise LLMError("LLM provider returned a non-string message content.")
    if text == "":
        finish = choice.get("finish_reason")
        usage = data.get("usage")
        reasoning_tokens = 0
        if isinstance(usage, dict):
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                reasoning_tokens = details.get("reasoning_tokens") or 0
        raise LLMError(
            "LLM provider returned empty content"
            + (f" (finish_reason={finish!r}" if finish else "")
            + (
                f", {reasoning_tokens} of {usage.get('completion_tokens', '?')} "
                "output tokens spent on reasoning"
                if reasoning_tokens
                else ""
            )
            + "). Reasoning models can spend the whole max_tokens budget on "
            "chain of thought: raise LLM_MAX_OUTPUT_TOKENS or set "
            "LLM_REASONING_EFFORT=low."
        )
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
