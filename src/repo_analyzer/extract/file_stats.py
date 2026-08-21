"""File statistics from the tree: counts, sizes, extension histogram.

Line counts are only computed for a small sample (the largest files) by
fetching raw content — the API cannot report lines without downloading
every file, which is out of scope for the deterministic layer.

``fetch_raw_fn`` is injectable so tests never touch the network.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..github_client import GitHubClient
from ..models import FileSize, FileStats, RepoRef, RepoTree
from .tree import VENDORED_PREFIXES, is_binary_or_lockfile

MAX_LARGEST_FILES = 15
MAX_LINE_COUNT_FILES = 8


def extract_file_stats(
    client: GitHubClient,
    ref: RepoRef,
    branch: str,
    tree: RepoTree,
    *,
    fetch_raw_fn: Callable[[RepoRef, str, str], str] | None = None,
) -> FileStats:
    """Aggregate blob sizes and extension counts from the tree.

    Vendored prefixes are excluded from the statistics (the raw tree in
    the fact base still contains everything).
    """
    fetch_raw = fetch_raw_fn or _fetch_raw

    blobs = [
        e
        for e in tree.entries
        if e.type == "blob"
        and e.size is not None
        and not _is_vendored(e.path)
    ]
    total_bytes = sum(e.size or 0 for e in blobs)
    by_extension = Counter(Path(e.path).suffix.lower() or "(none)" for e in blobs)
    largest = sorted(blobs, key=lambda e: e.size or 0, reverse=True)[:MAX_LARGEST_FILES]

    line_counts: dict[str, int] = {}
    for entry in largest[:MAX_LINE_COUNT_FILES]:
        if is_binary_or_lockfile(entry.path):
            continue  # decoding binaries produces garbage "lines"
        try:
            content = fetch_raw(ref, branch, entry.path)
            line_counts[entry.path] = len(content.splitlines())
        except Exception:
            continue  # raw fetch is best-effort; missing counts are not fatal

    return FileStats(
        total_files=len(blobs),
        total_bytes=total_bytes,
        files_by_extension=dict(by_extension.most_common()),
        largest_files=[FileSize(path=e.path, size_bytes=e.size or 0) for e in largest],
        line_counts=line_counts,
    )


def _is_vendored(path: str) -> bool:
    head = path.split("/")[0]
    return any(head == prefix or path.startswith(prefix + "/") for prefix in VENDORED_PREFIXES)


def _fetch_raw(ref: RepoRef, branch: str, path: str) -> str:
    """Fetch file content from raw.githubusercontent.com.

    Not counted against the API rate limit. Uses the branch ref, matching
    the tree that was fetched.
    """
    url = (
        f"https://raw.githubusercontent.com/{ref.api_path}/"
        f"{urllib.parse.quote(branch)}/{urllib.parse.quote(path)}"
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")
