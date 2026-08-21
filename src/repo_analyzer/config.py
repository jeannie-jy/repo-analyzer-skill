"""Environment-based configuration.

All runtime configuration flows through this module so that no API key or
provider URL is ever hard-coded in the codebase. Values are read from the
environment once, at startup, and passed down explicitly.

Secrets are never logged or echoed back by the CLI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .errors import ConfigError

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_TOKEN_BUDGET = 40_000
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_REPORT_LANGUAGE = "en"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings, populated from environment variables.

    Construct via ``Settings.from_env()``; tests may inject a mapping to
    simulate any environment without touching the real one.
    """

    github_token: str | None = None
    github_api_url: str = DEFAULT_GITHUB_API_URL

    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: str | None = None
    llm_model: str = DEFAULT_LLM_MODEL

    report_language: str = DEFAULT_REPORT_LANGUAGE
    output_dir: str = DEFAULT_OUTPUT_DIR
    token_budget: int = DEFAULT_TOKEN_BUDGET
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build Settings from ``os.environ`` or an injected mapping.

        Raises ``ConfigError`` for malformed values (e.g. a non-integer
        TOKEN_BUDGET) so misconfiguration fails fast at startup.
        """
        env = os.environ if env is None else env

        def get(*names: str) -> str | None:
            for name in names:
                value = env.get(name)
                if value:
                    return value.strip()
            return None

        token_budget = DEFAULT_TOKEN_BUDGET
        if (raw := get("TOKEN_BUDGET")) is not None:
            try:
                token_budget = int(raw)
            except ValueError as exc:
                raise ConfigError(
                    f"TOKEN_BUDGET must be an integer, got {raw!r}"
                ) from exc

        return cls(
            github_token=get("GITHUB_TOKEN"),
            github_api_url=get("GITHUB_API_URL") or DEFAULT_GITHUB_API_URL,
            llm_base_url=get("LLM_BASE_URL", "OPENAI_BASE_URL") or DEFAULT_LLM_BASE_URL,
            llm_api_key=get("LLM_API_KEY", "OPENAI_API_KEY"),
            llm_model=get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            report_language=(get("REPORT_LANGUAGE") or DEFAULT_REPORT_LANGUAGE).lower(),
            output_dir=get("OUTPUT_DIR") or DEFAULT_OUTPUT_DIR,
            token_budget=token_budget,
            log_level=(get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper(),
        )

    def require_llm(self) -> None:
        """Raise ``ConfigError`` when an LLM call is needed but not configured."""
        if not self.llm_api_key:
            raise ConfigError(
                "LLM API key is missing. Set LLM_API_KEY (or OPENAI_API_KEY) "
                "in the environment."
            )
