"""Smoke tests for the Phase 2 skeleton: package, config, models, CLI tree."""

import pytest

from repo_analyzer import __version__
from repo_analyzer.cli import _build_parser, main
from repo_analyzer.config import Settings
from repo_analyzer.errors import ConfigError, InputError
from repo_analyzer.github_client import (
    AuthError,
    ForbiddenError,
    RateLimitError,
    RepoNotFoundError,
    map_http_error,
)
from repo_analyzer.models import RepoRef

EMPTY_ENV = {"PATH": "/bin"}


# ---------------------------------------------------------------------------
# package / version
# ---------------------------------------------------------------------------


def test_version() -> None:
    assert __version__ == "0.1.0"


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_settings_defaults() -> None:
    s = Settings.from_env(EMPTY_ENV)
    assert s.github_api_url == "https://api.github.com"
    assert s.llm_base_url == "https://api.openai.com/v1"
    assert s.token_budget == 40_000
    assert s.report_language == "en"
    assert s.log_level == "INFO"


def test_settings_reads_env_values() -> None:
    s = Settings.from_env(
        {
            "GITHUB_TOKEN": "ghp_abc",
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_MODEL": "deepseek-chat",
            "TOKEN_BUDGET": "8000",
            "REPORT_LANGUAGE": "zh",
        }
    )
    assert s.github_token == "ghp_abc"
    assert s.llm_base_url == "https://api.deepseek.com/v1"
    assert s.llm_model == "deepseek-chat"
    assert s.token_budget == 8000
    assert s.report_language == "zh"


def test_settings_accepts_openai_fallback_env_names() -> None:
    s = Settings.from_env({"OPENAI_BASE_URL": "https://x.example/v1", "OPENAI_API_KEY": "k"})
    assert s.llm_base_url == "https://x.example/v1"
    assert s.llm_api_key == "k"


def test_settings_rejects_bad_token_budget() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"TOKEN_BUDGET": "abc"})


def test_settings_require_llm_raises_without_key() -> None:
    with pytest.raises(ConfigError, match="LLM API key"):
        Settings.from_env(EMPTY_ENV).require_llm()


def test_settings_require_llm_passes_with_key() -> None:
    Settings.from_env({"LLM_API_KEY": "k"}).require_llm()


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


def test_repo_ref_from_url() -> None:
    ref = RepoRef.from_url("https://github.com/pallets/flask")
    assert (ref.owner, ref.repo) == ("pallets", "flask")
    assert ref.api_path == "pallets/flask"


def test_repo_ref_from_url_with_suffix_and_git() -> None:
    ref = RepoRef.from_url("https://github.com/pallets/flask.git/tree/main/src")
    assert (ref.owner, ref.repo) == ("pallets", "flask")


def test_repo_ref_rejects_non_github_url() -> None:
    with pytest.raises(InputError):
        RepoRef.from_url("https://example.com/foo/bar")


def test_repo_ref_rejects_garbage() -> None:
    with pytest.raises(InputError):
        RepoRef.from_url("not a url")


def test_repo_ref_local_path(tmp_path) -> None:
    ref = RepoRef.from_local_path(str(tmp_path))
    assert ref.owner == "local"
    assert ref.local_path == tmp_path.resolve()


def test_repo_ref_local_path_missing(tmp_path) -> None:
    with pytest.raises(InputError):
        RepoRef.from_local_path(str(tmp_path / "nope"))


def test_repo_ref_workdir() -> None:
    ref = RepoRef.from_url("https://github.com/Test_Org/My-Repo")
    assert ref.workdir("out") == __import__("pathlib").Path(
        "out/repos/test-org/my-repo"
    )


# ---------------------------------------------------------------------------
# github client error mapping
# ---------------------------------------------------------------------------


def test_map_http_error_404() -> None:
    err = map_http_error(404)
    assert isinstance(err, RepoNotFoundError)
    assert err.status_code == 404


def test_map_http_error_401() -> None:
    assert isinstance(map_http_error(401), AuthError)


def test_map_http_error_429_with_retry_after() -> None:
    err = map_http_error(429, headers={"Retry-After": "37"})
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 37.0


def test_map_http_error_403_rate_limit_body() -> None:
    err = map_http_error(403, body='{"message": "API rate limit exceeded"}')
    assert isinstance(err, RateLimitError)


def test_map_http_error_403_forbidden() -> None:
    assert isinstance(map_http_error(403), ForbiddenError)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_cli_version_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


def test_cli_unknown_command_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["bogus-command"])
    assert exc_info.value.code == 2


def test_cli_extract_validates_input_before_network(capsys) -> None:
    # URL parsing happens before any API call, so garbage input fails
    # fast without touching the network.
    code = main(["extract", "not-a-url"])
    assert code == 2
    assert "Input error" in capsys.readouterr().err


def test_parser_exposes_all_subcommands() -> None:
    parser = _build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert set(choices) == {
        "extract",
        "analyze",
        "sample-code",
        "validate-report",
        "verify-evidence",
    }
