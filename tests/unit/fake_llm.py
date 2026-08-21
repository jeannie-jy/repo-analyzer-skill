"""Scripted LLMClient fake for pipeline tests — no network, no mocks."""

from __future__ import annotations

from repo_analyzer.config import Settings


class FakeLLM:
    """Returns queued responses verbatim; records every call.

    ``responses`` may contain strings (returned in order, last one
    repeats) or exceptions (raised). ``settings`` mirrors what a real
    client exposes so the pipeline can read the model name from it.
    """

    def __init__(
        self,
        responses: list[str | Exception],
        *,
        settings: Settings | None = None,
    ) -> None:
        self.responses = list(responses)
        self.settings = settings or Settings(llm_model="fake-model")
        self.calls: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        self.calls.append(messages)
        next_response = self.responses.pop(0) if self.responses else self.responses[-1]
        if isinstance(next_response, Exception):
            raise next_response
        return next_response
