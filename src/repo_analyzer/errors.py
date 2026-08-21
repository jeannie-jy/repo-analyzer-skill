"""Typed error hierarchy for repo-analyzer.

Every failure in the pipeline maps to exactly one error type so callers
(CLI, agent, eval harness) can branch on the *kind* of failure instead of
parsing messages. See docs/ARCHITECTURE.md §9 for the three-way strategy:
input errors, upstream errors, environment errors.
"""

from __future__ import annotations


class RepoAnalyzerError(Exception):
    """Base class for all repo-analyzer errors."""


# ---------------------------------------------------------------------------
# Input errors — bad user input, fail fast with a clear message
# ---------------------------------------------------------------------------


class InputError(RepoAnalyzerError):
    """The provided repository URL / path is invalid or unsupported."""


# ---------------------------------------------------------------------------
# Upstream errors — GitHub API / network
# ---------------------------------------------------------------------------


class GitHubAPIError(RepoAnalyzerError):
    """A GitHub API request failed for a non-transient reason."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RepoNotFoundError(GitHubAPIError):
    """The repository does not exist (HTTP 404)."""


class AuthError(GitHubAPIError):
    """Authentication failed (HTTP 401)."""


class ForbiddenError(GitHubAPIError):
    """Authenticated but not allowed (HTTP 403, excluding rate limits)."""


class RateLimitError(GitHubAPIError):
    """API rate limit exceeded (HTTP 429, or 403 with a rate-limit body)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class NetworkError(GitHubAPIError):
    """Connection-level failure (DNS, timeout, reset)."""


# ---------------------------------------------------------------------------
# Pipeline errors
# ---------------------------------------------------------------------------


class ExtractionError(RepoAnalyzerError):
    """A deterministic extraction step failed."""


class LLMError(RepoAnalyzerError):
    """An LLM call failed or returned invalid output."""


class ReportValidationError(RepoAnalyzerError):
    """A generated report failed schema validation."""


class ConfigError(RepoAnalyzerError):
    """Missing or invalid configuration."""
