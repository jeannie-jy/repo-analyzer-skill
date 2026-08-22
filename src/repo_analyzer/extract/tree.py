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
from pathlib import Path

from ..github_client import GitHubClient
from ..models import RepoRef, RepoTree, TreeEntry
from .local import SnapshotEntry, git_snapshot, walk_snapshot

DEFAULT_MAX_ENTRIES = 20_000
MAX_TOP_LEVEL_DIRS_TO_EXPAND = 30

# Re-exported from extract.ignore so existing consumers keep importing
# from tree.py without change.
from .ignore import (  # noqa: E402
    BINARY_EXTENSIONS,
    LOCKFILE_NAMES,
    VENDORED_PREFIXES,
    is_binary_or_lockfile,
)


def extract_tree(
    client: GitHubClient,
    ref: RepoRef,
    branch: str,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> RepoTree:
    """Build the repository tree for ``branch``.

    Local refs read the on-disk snapshot (git-tracked content at HEAD,
    or a filesystem scan for non-git dirs) and never touch the network.
    Raises the typed GitHub errors (404 / rate limit / network) for
    remote refs; the pipeline turns those into warnings for the fact base.
    """
    if ref.local_path is not None:
        return _local_tree(ref.local_path, max_entries=max_entries)

    data = client.get_json(
        f"repos/{ref.api_path}/git/trees/{urllib.parse.quote(branch)}",
        params={"recursive": 1},
    )
    truncated = bool(data.get("truncated"))
    entries = _parse_entries(data.get("tree", []))

    if truncated:
        entries = _expand_two_levels(client, ref, branch)

    return _assemble(entries, max_entries=max_entries, truncated=truncated)


def _local_tree(root: Path, *, max_entries: int) -> RepoTree:
    """Tree from a local directory: git snapshot, or walk fallback."""
    entries = git_snapshot(root)
    if entries is None:
        entries = walk_snapshot(root)
    return _assemble(_snapshot_to_entries(entries), max_entries=max_entries)


def _snapshot_to_entries(snapshot: list[SnapshotEntry]) -> list[TreeEntry]:
    """Snapshot items -> TreeEntry, deriving directory nodes from paths."""
    entries: list[TreeEntry] = []
    dir_paths: set[str] = set()
    for item in snapshot:
        parts = item.path.split("/")
        for i in range(1, len(parts)):
            dir_paths.add("/".join(parts[:i]))
    entries.extend(
        TreeEntry(path=path, type="tree") for path in sorted(dir_paths)
    )
    for item in snapshot:
        if item.type == "tree":
            # submodule directory nodes (also present in git_snapshot)
            if item.path not in dir_paths:
                entries.append(TreeEntry(path=item.path, type="tree", sha=item.sha))
        else:
            entries.append(
                TreeEntry(path=item.path, type="blob", size=item.size, sha=item.sha)
            )
    return entries


def _assemble(entries: list[TreeEntry], *, max_entries: int, truncated: bool = False) -> RepoTree:
    """Shared tree assembly: sort, cap, derive top-level lists."""
    entries = sorted(entries, key=lambda e: e.path)
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
