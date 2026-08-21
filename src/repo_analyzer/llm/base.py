"""Provider abstraction for LLM calls.

The pipeline depends on the structural :class:`LLMClient` protocol, not
on any concrete vendor. A message is a plain ``{"role": ..., "content": ...}``
dict, matching every chat-completions API in existence, so fakes are
trivial to write.

:class:`OpenAICompatClient` (the reference implementation) also satisfies
this protocol structurally — no subclassing needed for tests.
"""

from __future__ import annotations

from typing import Protocol

# A chat message: {"role": "system"|"user"|"assistant", "content": str}
LLMMessage = dict[str, str]

DEFAULT_TEMPERATURE = 0.2  # low: we want grounded reasoning, not creativity
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class LLMClient(Protocol):
    """Anything that can complete a chat message list. Structural typing."""

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> str:
        """Return the assistant's reply text.

        Raises :class:`repo_analyzer.errors.LLMError` on provider errors,
        rate limits after retries, or malformed responses.
        """
        ...
