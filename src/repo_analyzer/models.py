"""Core data contracts (input ref, artifact layout).

These dataclasses are the *contract* between the deterministic extraction
layer and the LLM reasoning layer. The full fact-base schema evolves with
the extract modules (Phase 3); here we pin down the input contract and the
artifact layout on disk so every phase writes to a stable location.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import InputError

GITHUB_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$"
)

# Names of the artifacts written under <output_dir>/repos/<owner>/<repo>/
FACTS_FILENAME = "repo_facts.json"
REPORT_FILENAME = "report.json"
REPORT_MD_FILENAME = "report.md"
SAMPLE_MANIFEST_FILENAME = "sample_manifest.json"


@dataclass(frozen=True)
class RepoRef:
    """A normalized reference to a GitHub repository (or a local copy).

    Attributes:
        owner: GitHub owner (org or user). ``"local"`` for local copies.
        repo: repository name.
        url: the original input, normalized.
        ref: branch / tag / sha to analyze; ``None`` = default branch.
        local_path: set when the analysis source is a local directory.
    """

    owner: str
    repo: str
    url: str
    ref: str | None = None
    local_path: Path | None = None

    @property
    def api_path(self) -> str:
        """Path component for GitHub REST calls: ``owner/repo``."""
        return f"{self.owner}/{self.repo}"

    @classmethod
    def from_url(cls, url: str, *, ref: str | None = None) -> "RepoRef":
        """Parse a GitHub URL into a ``RepoRef``.

        Accepts ``https://github.com/owner/repo[.git][/suffix]``. A URL
        suffix (e.g. ``/tree/main/src``) is ignored — the analysis always
        targets the repository root.
        """
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
        return cls(
            owner="local",
            repo=local.name,
            url=str(local),
            ref=None,
            local_path=local,
        )

    def workdir(self, base: str | Path) -> Path:
        """Artifact directory for this repo under a base output dir.

        Lowercased owner/repo keep paths portable across filesystems.
        """
        safe_owner = self.owner.lower().replace("_", "-")
        safe_repo = self.repo.lower().replace("_", "-")
        return Path(base) / "repos" / safe_owner / safe_repo
