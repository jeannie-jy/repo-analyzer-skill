"""Environment parsing: Settings.from_env, dotenv merging, fail-fast."""

from __future__ import annotations

from repo_analyzer.config import Settings, load_dotenv
from repo_analyzer.errors import ConfigError

import pytest


def test_from_env_reads_all_keys() -> None:
    settings = Settings.from_env(
        {
            "GITHUB_TOKEN": "ghp_abc",
            "GITHUB_API_URL": "https://ghe.example.com/api/v3",
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_API_KEY": "sk-test",
            "LLM_MODEL": "deepseek-chat",
            "REPORT_LANGUAGE": "zh",
            "OUTPUT_DIR": "tmp/out",
            "TOKEN_BUDGET": "12345",
            "LOG_LEVEL": "debug",
        }
    )
    assert settings.github_token == "ghp_abc"
    assert settings.github_api_url == "https://ghe.example.com/api/v3"
    assert settings.llm_base_url == "https://api.deepseek.com/v1"
    assert settings.llm_api_key == "sk-test"
    assert settings.llm_model == "deepseek-chat"
    assert settings.report_language == "zh"
    assert settings.output_dir == "tmp/out"
    assert settings.token_budget == 12345
    assert settings.log_level == "DEBUG"


def test_from_env_defaults() -> None:
    settings = Settings.from_env({})
    assert settings.github_token is None
    assert settings.llm_api_key is None
    assert settings.github_api_url == "https://api.github.com"
    assert settings.llm_base_url == "https://api.openai.com/v1"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.token_budget == 40_000


def test_openai_api_key_alias_is_accepted() -> None:
    settings = Settings.from_env({"OPENAI_API_KEY": "sk-alias", "OPENAI_BASE_URL": "https://x/v1"})
    assert settings.llm_api_key == "sk-alias"
    assert settings.llm_base_url == "https://x/v1"


def test_bad_token_budget_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="TOKEN_BUDGET"):
        Settings.from_env({"TOKEN_BUDGET": "not-a-number"})


def test_require_llm_raises_when_key_missing() -> None:
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        Settings.from_env({}).require_llm()
    Settings.from_env({"LLM_API_KEY": "sk-x"}).require_llm()  # no raise


def test_load_dotenv_parses_lines_comments_and_quotes(tmp_path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "# comment line\n"
        "GITHUB_TOKEN = ghp_abc   \n"
        'LLM_API_KEY="sk-quoted"\n'
        "EMPTY=\n"
        "NO_EQUALS_LINE\n"
        "\n",
        encoding="utf-8",
    )
    parsed = load_dotenv(env_file)
    assert parsed["GITHUB_TOKEN"] == "ghp_abc"
    assert parsed["LLM_API_KEY"] == "sk-quoted"
    assert parsed["EMPTY"] == ""  # explicitly empty values are kept as-is
    assert "NO_EQUALS_LINE" not in parsed


def test_load_dotenv_missing_file_is_empty() -> None:
    assert load_dotenv("definitely/not/here.env") == {}


def test_real_environment_wins_over_dotenv(monkeypatch) -> None:
    from repo_analyzer.config import _merge_dotenv

    monkeypatch.setattr(
        "repo_analyzer.config.load_dotenv",
        lambda path=None: {"LLM_API_KEY": "from-file", "GITHUB_TOKEN": "file-token"},
    )
    merged = _merge_dotenv({"LLM_API_KEY": "from-env"})
    assert merged["LLM_API_KEY"] == "from-env"  # env wins
    assert merged["GITHUB_TOKEN"] == "file-token"  # file fills the gap
