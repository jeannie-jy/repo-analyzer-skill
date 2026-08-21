"""README extraction: path, deterministic excerpt, quickstart commands.

Quickstart commands are found by scanning fenced code blocks for lines
that start with a well-known command prefix. This is deliberately crude —
it only feeds the LLM with *candidates*, and the raw excerpt is available
for anything the regex misses.
"""

from __future__ import annotations

import base64
import re

from ..github_client import GitHubClient
from ..errors import RepoNotFoundError
from ..models import ReadmeInfo, RepoRef

EXCERPT_CHARS = 2000

_COMMAND_PREFIX_RE = re.compile(
    r"^(pip install|pipenv install|uv (add|sync|run)|poetry install|npm install"
    r"|npm run|npx |yarn |pnpm |docker (run|build|compose)|make |cargo (run|build)"
    r"|go run|go build|python -m|flask run|uvicorn|gunicorn|celery |bundle install"
    r"|mix deps\.get|iex -S|./configure|cmake |rails |pnpm )"
)


def extract_readme(client: GitHubClient, ref: RepoRef, branch: str) -> ReadmeInfo:
    """Fetch the repository README (404 = no README, not an error)."""
    try:
        data = client.get_json(
            f"repos/{ref.api_path}/readme", params={"ref": branch}
        )
    except RepoNotFoundError:
        return ReadmeInfo()
    if not isinstance(data, dict) or not data.get("content"):
        return ReadmeInfo(path=data.get("path") if isinstance(data, dict) else None)
    try:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ReadmeInfo(path=data.get("path"))
    return ReadmeInfo(
        path=data.get("path"),
        excerpt=content[:EXCERPT_CHARS],
        quickstart_commands=_extract_quickstart(content),
    )


def _extract_quickstart(content: str) -> list[str]:
    """Scan fenced code blocks for command-prefixed lines."""
    commands: list[str] = []
    in_block = False
    for line in content.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        stripped = line.strip()
        if _COMMAND_PREFIX_RE.match(stripped):
            commands.append(stripped)
    return commands[:10]
