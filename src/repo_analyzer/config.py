"""Environment-based configuration.

All runtime configuration flows through this module so that no API key or
provider URL is ever hard-coded in the codebase. Values are read from the
environment once, at startup, and passed down explicitly.

A ``.env`` file in the working directory is loaded first (KEY=VALUE lines,
``#`` comments, no interpolation) — real environment variables always
take precedence over the file, and the file never overrides an exported
value. Secrets are never logged or echoed back by the CLI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import ConfigError

DOTENV_FILENAME = ".env"

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_MAX_OUTPUT_TOKENS = 4096
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
    # Reasoning models (e.g. DeepSeek V4) consume max_tokens on chain of
    # thought before producing any content; raise this for them. None
    # sends no reasoning_effort field at all (plain chat models ignore it
    # and some providers reject unknown fields).
    llm_max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    llm_reasoning_effort: str | None = None

    report_language: str = DEFAULT_REPORT_LANGUAGE
    output_dir: str = DEFAULT_OUTPUT_DIR
    token_budget: int = DEFAULT_TOKEN_BUDGET
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build Settings from ``os.environ`` or an injected mapping.

        When reading the real environment, a ``.env`` file next to the
        working directory is merged in first (see :func:`load_dotenv`).
        An injected mapping is used verbatim — tests simulate any
        environment without touching the real one. Raises ``ConfigError``
        for malformed values (e.g. a non-integer TOKEN_BUDGET) so
        misconfiguration fails fast at startup.
        """
        env = _merge_dotenv(os.environ) if env is None else dict(env)

        def get(*names: str) -> str | None:
            for name in names:
                value = env.get(name)
                if value:
                    return value.strip()
            return None

        def get_int(name: str, default: int) -> int:
            raw = get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc

        return cls(
            github_token=get("GITHUB_TOKEN"),
            github_api_url=get("GITHUB_API_URL") or DEFAULT_GITHUB_API_URL,
            llm_base_url=get("LLM_BASE_URL", "OPENAI_BASE_URL") or DEFAULT_LLM_BASE_URL,
            llm_api_key=get("LLM_API_KEY", "OPENAI_API_KEY"),
            llm_model=get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            llm_max_output_tokens=get_int("LLM_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
            llm_reasoning_effort=get("LLM_REASONING_EFFORT"),
            report_language=(get("REPORT_LANGUAGE") or DEFAULT_REPORT_LANGUAGE).lower(),
            output_dir=get("OUTPUT_DIR") or DEFAULT_OUTPUT_DIR,
            token_budget=get_int("TOKEN_BUDGET", DEFAULT_TOKEN_BUDGET),
            log_level=(get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper(),
        )

    def require_llm(self) -> None:
        """Raise ``ConfigError`` when an LLM call is needed but not configured."""
        if not self.llm_api_key:
            raise ConfigError(
                "LLM API key is missing. Set LLM_API_KEY (or OPENAI_API_KEY) "
                "in the environment or in a .env file."
            )


def load_dotenv(path: str | Path = DOTENV_FILENAME) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` dotenv file into a dict (never overriding).

    ``#`` comments and blank lines are skipped; values are stripped of
    surrounding quotes and whitespace. A missing file yields ``{}`` — a
    dotenv is an optional convenience, never a requirement.
    """
    dotenv = Path(path)
    result: dict[str, str] = {}
    if not dotenv.is_file():
        return result
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        result[key] = value
    return result


def _merge_dotenv(env: Mapping[str, str]) -> dict[str, str]:
    """Real environment wins over the ``.env`` file, always."""
    merged = dict(load_dotenv())
    merged.update(env)
    return merged
