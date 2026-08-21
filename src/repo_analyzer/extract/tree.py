"""Directory tree extraction via the git trees API (recursive).

Handles the two ways GitHub can truncate a tree:

1. ``truncated: true`` in the API response — the recursive response is
   unusable; we fall back to a two-level expansion via the contents API
   (root + each top-level directory) and mark the tree as truncated.
2. Our own cap (``max_entries``) — keeps the fact base a sane size;
   the tree is marked truncated so downstream consumers know the list
   is not complete.

The fact layer never *deletes* vendored entries (consumers filter via
``excluded_prefixes``) — data loss is the consumer's decision, not ours.
"""

from __future__ import annotations

import urllib.parse

from ..github_client import GitHubClient
from ..models import RepoRef, RepoTree, TreeEntry

DEFAULT_MAX_ENTRIES = 20_000
MAX_TOP_LEVEL_DIRS_TO_EXPAND = 30

# Paths we flag as vendored / generated. Kept as *prefixes* so consumers
# can filter consistently (dependencies, file stats, sampling).
VENDORED_PREFIXES = (
    ".git",
    ".github",
    ".gitlab",
    ".idea",
    ".vscode",
    ".venv",
    ".next",
    ".nuxt",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".ruff_cache",
    "node_modules",
    "vendor",
    "venv",
    "env",
    "dist",
    "build",
    "target",
    "coverage",
    "htmlcov",
)


def extract_tree(
    client: GitHubClient,
    ref: RepoRef,
    branch: str,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> RepoTree:
    """Build the repository tree for ``branch``.

    Raises the typed GitHub errors (404 / rate limit / network); the
    pipeline turns those into warnings for the fact base.
    """
    data = client.get_json(
        f"repos/{ref.api_path}/git/trees/{urllib.parse.quote(branch)}",
        params={"recursive": 1},
    )
    truncated = bool(data.get("truncated"))
    entries = _parse_entries(data.get("tree", []))

    if truncated:
        entries = _expand_two_levels(client, ref, branch)

    if len(entries) > max_entries:
        entries = entries[:max_entries]
        truncated = True

    return RepoTree(
        truncated=truncated,
        entries=entries,
        top_level_dirs=sorted({e.path.split("/")[0] for e in entries if e.type == "tree"}),
        top_level_files=sorted(e.path for e in entries if e.type == "blob" and "/" not in e.path),
        excluded_prefixes=list(VENDORED_PREFIXES),
        max_entries=max_entries,
    )


def _parse_entries(raw: list[dict]) -> list[TreeEntry]:
    entries = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        entries.append(
            TreeEntry(
                path=item["path"],
                type=item.get("type", "blob"),
                size=item.get("size") if item.get("type") == "blob" else None,
                sha=item.get("sha", ""),
            )
        )
    return entries


def _expand_two_levels(client: GitHubClient, ref: RepoRef, branch: str) -> list[TreeEntry]:
    """Fallback for truncated trees: root level + one level of directories.

    Uses the contents API, which returns one directory listing per call.
    """
    entries: list[TreeEntry] = []

    def add_listing(prefix: str) -> None:
        try:
            data = client.get_json(
                f"repos/{ref.api_path}/contents/{prefix}",
                params={"ref": branch},
            )
        except Exception:
            return  # partial listings are better than none
        if not isinstance(data, list):
            return
        for item in data:
            path = item.get("path", "")
            entries.append(
                TreeEntry(
                    path=path,
                    type=item.get("type", "blob"),
                    size=item.get("size") if item.get("type") == "blob" else None,
                    sha=item.get("sha", ""),
                )
            )

    add_listing("")  # root (contents API accepts "" for the root)
    top_dirs = [e.path for e in entries if e.type == "tree"]
    for dir_path in top_dirs[:MAX_TOP_LEVEL_DIRS_TO_EXPAND]:
        add_listing(dir_path)
    return entries
