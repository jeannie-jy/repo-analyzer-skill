"""Language statistics — one GET on ``/repos/{owner}/{repo}/languages``."""

from __future__ import annotations

from pathlib import Path

from ..github_client import GitHubClient
from ..models import LanguageShare, LanguageStats, RepoRef
from .local import git_snapshot, walk_snapshot
from .tree import VENDORED_PREFIXES, is_binary_or_lockfile

# Extension -> language name for the local approximation. GitHub's
# linguist detection is not reproducible locally, so we map common
# extensions and skip anything unmapped — never emit ".svg" as a name.
_EXTENSION_NAMES = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "JavaScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C", ".cpp": "C++",
    ".hpp": "C++", ".cs": "C#", ".swift": "Swift", ".kt": "Kotlin",
    ".scala": "Scala", ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell",
    ".md": "Markdown", ".rst": "Markdown", ".json": "JSON", ".toml": "TOML",
    ".yaml": "YAML", ".yml": "YAML", ".xml": "XML", ".html": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".vue": "Vue", ".sql": "SQL",
    ".lua": "Lua", ".pl": "Perl", ".r": "R", ".dart": "Dart",
    ".gradle": "Groovy", ".tf": "HCL", ".dockerfile": "Dockerfile",
}


def extract_languages(client: GitHubClient, ref: RepoRef) -> LanguageStats:
    """Fetch byte counts per language and compute percentages.

    ``languages`` API returns ``{name: bytes}`` ordered by bytes
    descending; we keep that order and add a one-decimal percentage.

    Local refs approximate with extension-based byte counts over the
    same snapshot the tree uses (vendored dirs and binary/lockfiles
    excluded, like linguist does).
    """
    if ref.local_path is not None:
        return _local_languages(ref.local_path)

    data = client.get_json(f"repos/{ref.api_path}/languages")
    if not isinstance(data, dict):
        return LanguageStats()
    total = sum(data.values())
    if total <= 0:
        return LanguageStats()
    shares = [
        LanguageShare(
            name=name,
            bytes=byte_count,
            percentage=round(byte_count / total * 100, 1),
        )
        for name, byte_count in sorted(data.items(), key=lambda kv: -kv[1])
    ]
    return LanguageStats(languages=shares)


def _local_languages(root: Path) -> LanguageStats:
    entries = git_snapshot(root)
    if entries is None:
        entries = walk_snapshot(root)

    by_name: dict[str, int] = {}
    for entry in entries:
        if entry.type != "blob" or entry.size is None:
            continue
        if _is_vendored(entry.path) or is_binary_or_lockfile(entry.path):
            continue
        name = _EXTENSION_NAMES.get(Path(entry.path).suffix.lower())
        if name is None:
            continue  # unmapped extension: skip rather than mislabel
        by_name[name] = by_name.get(name, 0) + entry.size

    total = sum(by_name.values())
    if total <= 0:
        return LanguageStats()
    shares = [
        LanguageShare(name=name, bytes=bytes_, percentage=round(bytes_ / total * 100, 1))
        for name, bytes_ in sorted(by_name.items(), key=lambda kv: -kv[1])
    ]
    return LanguageStats(languages=shares)


def _is_vendored(path: str) -> bool:
    head = path.split("/")[0]
    return any(head == prefix or path.startswith(prefix + "/") for prefix in VENDORED_PREFIXES)
