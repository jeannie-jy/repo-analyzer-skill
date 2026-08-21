"""Core data contracts: input ref + the fact base (schema v1).

The fact base is the single contract between the deterministic extraction
layer and every downstream consumer (LLM prompts, report schema, eval).
Nothing below this layer ever re-queries GitHub: prompts and reports are
built exclusively from ``RepoFacts``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import InputError

FACTS_SCHEMA_VERSION = "1.0"
TOOL_NAME = "repo-analyzer"

GITHUB_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$"
)

# Names of the artifacts written under <output_dir>/repos/<owner>/<repo>/
FACTS_FILENAME = "repo_facts.json"
ANALYSIS_FILENAME = "analysis.json"
REPORT_FILENAME = "report.json"
REPORT_MD_FILENAME = "report.md"
SAMPLE_MANIFEST_FILENAME = "sample_manifest.json"


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoRef:
    """A normalized reference to a GitHub repository (or a local copy)."""

    owner: str
    repo: str
    url: str
    ref: str | None = None  # branch / tag / sha; None = default branch
    local_path: Path | None = None

    @property
    def api_path(self) -> str:
        """Path component for GitHub REST calls: ``owner/repo``."""
        return f"{self.owner}/{self.repo}"

    @classmethod
    def from_url(cls, url: str, *, ref: str | None = None) -> "RepoRef":
        """Parse a GitHub URL into a ``RepoRef`` (suffixes are ignored)."""
        match = GITHUB_URL_RE.match(url.strip())
        if not match:
            raise InputError(
                f"Not a GitHub repository URL: {url!r}. "
                "Expected https://github.com/owner/repo"
            )
        return cls(
            owner=match.group("owner"),
            repo=match.group("repo"),
            url=url.strip(),
            ref=ref,
        )

    @classmethod
    def from_local_path(cls, path: str) -> "RepoRef":
        """Wrap an existing local directory as an analysis source."""
        local = Path(path).expanduser().resolve()
        if not local.is_dir():
            raise InputError(f"Local repository path does not exist: {path}")
        return cls(owner="local", repo=local.name, url=str(local), ref=None, local_path=local)

    def workdir(self, base: str | Path) -> Path:
        """Artifact directory for this repo under a base output dir."""
        safe_owner = self.owner.lower().replace("_", "-")
        safe_repo = self.repo.lower().replace("_", "-")
        return Path(base) / "repos" / safe_owner / safe_repo


# ---------------------------------------------------------------------------
# Fact base (schema v1) — produced by the extract modules, consumed by the
# LLM reasoning layer. Every dataclass carries a default so partial facts
# (degraded runs) serialize cleanly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoMetadata:
    description: str | None = None
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    license_name: str | None = None
    topics: list[str] = field(default_factory=list)
    created_at: str | None = None
    pushed_at: str | None = None
    homepage: str | None = None
    is_archived: bool = False
    is_fork: bool = False
    size_kb: int = 0
    default_branch: str = "main"
    open_issues_count: int = 0


@dataclass(frozen=True)
class TreeEntry:
    path: str
    type: str  # "blob" | "tree"
    size: int | None = None  # None for directories
    sha: str = ""


@dataclass(frozen=True)
class RepoTree:
    truncated: bool = False
    entries: list[TreeEntry] = field(default_factory=list)
    top_level_dirs: list[str] = field(default_factory=list)
    top_level_files: list[str] = field(default_factory=list)
    excluded_prefixes: list[str] = field(default_factory=list)
    max_entries: int = 0


@dataclass(frozen=True)
class LanguageShare:
    name: str
    bytes: int
    percentage: float  # 0-100, one decimal


@dataclass(frozen=True)
class LanguageStats:
    languages: list[LanguageShare] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(l.bytes for l in self.languages)


@dataclass(frozen=True)
class ManifestInfo:
    path: str
    kind: str  # "npm" | "pip" | "pyproject" | "pipenv" | "cargo" | "go" | "bundler" | "composer" | "setuptools" | "dart"
    format: str  # "json" | "toml" | "text" | "regex" | "yaml"


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str | None
    manifest: str
    category: str = "runtime"  # "runtime" | "dev" | "unknown"


@dataclass(frozen=True)
class UnparseableManifest:
    path: str
    reason: str


@dataclass(frozen=True)
class Dependencies:
    direct: list[Dependency] = field(default_factory=list)
    unparseable: list[UnparseableManifest] = field(default_factory=list)


ENTRYPOINT_KINDS = (
    "cli",
    "http_server",
    "worker",
    "library_entry",
    "entrypoint_script",
    "build_entry",
    "container_entry",
)


@dataclass(frozen=True)
class EntrypointCandidate:
    path: str | None
    kind: str
    heuristic: str  # what the deterministic rule matched
    confidence: float  # 0-1, from the heuristic alone (LLM re-ranks later)
    invocation: str | None = None


@dataclass(frozen=True)
class Contributor:
    login: str
    contributions: int


@dataclass(frozen=True)
class GitStats:
    last_commit_at: str | None = None
    commits_last_30d: int | None = None
    commits_30d_capped: bool = False  # True when >=100 and we stopped counting
    top_contributors: list[Contributor] = field(default_factory=list)
    open_issues: int = 0
    open_pulls: int | None = None


@dataclass(frozen=True)
class FileSize:
    path: str
    size_bytes: int


@dataclass(frozen=True)
class FileStats:
    total_files: int = 0
    total_bytes: int = 0
    files_by_extension: dict[str, int] = field(default_factory=dict)
    largest_files: list[FileSize] = field(default_factory=list)
    line_counts: dict[str, int] = field(default_factory=dict)  # only for a sampled subset


@dataclass(frozen=True)
class ReadmeInfo:
    path: str | None = None
    excerpt: str = ""  # first N chars, deterministic truncation
    quickstart_commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepoFacts:
    """The full deterministic fact base — schema v1. Serialized as JSON."""

    schema_version: str = FACTS_SCHEMA_VERSION
    repo: dict = field(default_factory=dict)  # owner/repo/url/ref/branch/ref_sha
    metadata: RepoMetadata = field(default_factory=RepoMetadata)
    tree: RepoTree = field(default_factory=RepoTree)
    languages: LanguageStats = field(default_factory=LanguageStats)
    manifests: list[ManifestInfo] = field(default_factory=list)
    dependencies: Dependencies = field(default_factory=Dependencies)
    entrypoints: list[EntrypointCandidate] = field(default_factory=list)
    git: GitStats = field(default_factory=GitStats)
    files: FileStats = field(default_factory=FileStats)
    readme: ReadmeInfo = field(default_factory=ReadmeInfo)
    warnings: list[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)  # tool + version + fetch time

    def to_dict(self) -> dict:
        return asdict(self)
