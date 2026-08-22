"""Local-directory snapshot helpers — the zero-network analysis source.

Two snapshot strategies, unified into one ``SnapshotEntry`` shape so the
tree / languages / readme modules cannot drift:

- ``git_snapshot`` — the tracked content at ``HEAD`` via ``git ls-tree``
  (a true snapshot from the object DB: sizes and shas match the remote
  tree API semantics; working-tree edits and untracked files are not
  part of it). Used when the directory is a git repository.
- ``walk_snapshot`` — a plain filesystem scan (includes untracked
  files) for directories that are not git repositories.

Windows notes: ``core.quotepath=false`` un-escapes non-ASCII paths that
git would otherwise render as octal escapes, and ``-z`` (NUL) splitting
handles spaces/newlines in file names; every path is normalized to
forward slashes here — a single normalization point before any consumer
sees a path.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ignore import VENDORED_PREFIXES

GIT_TIMEOUT_SECONDS = 30
MAX_LOCAL_FILE_BYTES = 1_000_000

# git file modes from ls-tree: symlinks point outside the blob model,
# submodules are commit pointers shown as directory nodes.
_SYMLINK_MODE = "120000"
_SUBMODULE_MODE = "160000"


@dataclass(frozen=True)
class SnapshotEntry:
    """One path in a local snapshot; paths are repo-relative with ``/``."""

    path: str
    type: str  # "blob" | "tree" (tree only for submodules)
    mode: str  # git mode ("" for walk)
    size: int | None  # blob bytes, None for directories
    sha: str  # blob sha from git; "" when not available


def git_cmd(root: Path, args: list[str], *, timeout: float = GIT_TIMEOUT_SECONDS) -> str | None:
    """Run ``git -C <root> <args>``; return stdout, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def is_git_repo(root: Path) -> bool:
    """True when git works in this directory (any HEAD state, incl. unborn)."""
    return git_cmd(root, ["rev-parse", "--git-dir"]) is not None


def git_snapshot(root: Path) -> list[SnapshotEntry] | None:
    """Tracked content at HEAD; None when not a git repository."""
    out = git_cmd(
        root,
        ["-c", "core.quotepath=false", "ls-tree", "-r", "-l", "HEAD", "-z"],
    )
    if out is None:
        return None
    entries: list[SnapshotEntry] = []
    for item in out.split("\0"):
        if not item:
            continue
        meta, _, path = item.partition("\t")
        # split() (not split(" ")): ls-tree right-pads the size column
        # with alignment spaces, so blank tokens are expected
        parts = meta.split()
        if len(parts) != 4:
            continue
        mode, kind, sha, size = parts
        if mode == _SYMLINK_MODE:
            continue  # symlink: content points outside the repo, no blob size
        if mode == _SUBMODULE_MODE:
            entries.append(
                SnapshotEntry(path=path, type="tree", mode=mode, size=None, sha=sha)
            )
            continue
        if kind == "tree":
            entries.append(
                SnapshotEntry(path=path, type="tree", mode=mode, size=None, sha=sha)
            )
            continue
        parsed_size = int(size) if size not in ("", "-") else None
        entries.append(
            SnapshotEntry(path=path, type="blob", mode=mode, size=parsed_size, sha=sha)
        )
    return entries


def walk_snapshot(root: Path) -> list[SnapshotEntry]:
    """Filesystem snapshot for non-git directories (untracked included).

    Hidden directories and ``VENDORED_PREFIXES`` are pruned; dirs and
    files are sorted so the output is deterministic run to run. Per-file
    stat failures (dangling symlinks, long paths) skip that file instead
    of failing the whole snapshot.
    """
    entries: list[SnapshotEntry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and d not in VENDORED_PREFIXES
        )
        rel = Path(dirpath).relative_to(root).as_posix()
        for name in sorted(filenames):
            if name.startswith("."):
                continue  # hidden files
            path = f"{rel}/{name}" if rel != "." else name
            try:
                size = os.path.getsize(Path(dirpath) / name)
            except OSError:
                continue
            entries.append(
                SnapshotEntry(path=path, type="blob", mode="", size=size, sha="")
            )
    return entries


def default_branch_local(root: Path) -> str:
    """HEAD's branch name; honest defaults when git is unavailable.

    ``git rev-parse --abbrev-ref HEAD`` handles worktrees (``.git`` as a
    file) and detached HEAD (yields ``HEAD``, which is honest). The raw
    ``.git/HEAD`` file read is only the non-git fallback.
    """
    out = git_cmd(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if out is not None and out.strip() and out.strip() != "HEAD":
        return out.strip()
    head = root / ".git" / "HEAD"
    try:
        content = head.read_text(encoding="utf-8", errors="replace").strip()
        if content.startswith("ref: "):
            return content[5:].rsplit("/", 1)[-1]
    except OSError:
        pass
    return "main"


def head_sha_local(root: Path) -> str | None:
    """HEAD's full sha; None when git is unavailable."""
    out = git_cmd(root, ["rev-parse", "HEAD"])
    if out is None or not out.strip():
        return None
    return out.strip()


def read_text_local(root: Path, path: str, max_bytes: int = MAX_LOCAL_FILE_BYTES) -> str | None:
    """Read a repo-relative file, capped like the remote contents API.

    None when missing or larger than ``max_bytes`` — callers treat None
    as "no information", never as an error (mirrors ``fetch_file_content``).
    """
    target = (root / path).resolve()
    try:
        if root.resolve() not in target.parents and target != root.resolve():
            return None  # path escapes the repo root
        if target.stat().st_size > max_bytes:
            return None
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
