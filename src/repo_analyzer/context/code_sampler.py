"""Budget-controlled code sampling (context management).

The LLM must never see the whole repository. :func:`sample_code` picks a
bounded, auditable set of files — entry points first (highest-evidence
signal), then manifests and the largest files — up to a token budget.

Token estimation is deliberately simple and conservative
(``chars // 4``); the manifest records the estimate per file so the
sample is reproducible and auditable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..github_client import GitHubClient, fetch_file_content
from ..models import RepoFacts, RepoRef
from ..extract.tree import VENDORED_PREFIXES

# A single file whose estimated size exceeds this share of the budget is
# skipped (truncated files confuse reasoning more than they help).
MAX_SINGLE_FILE_BUDGET_SHARE = 0.25


@dataclass(frozen=True)
class SampledFile:
    path: str
    size_bytes: int
    reason: str  # why this file was chosen, e.g. "entrypoint: cli (0.95)"
    token_estimate: int
    content: str


@dataclass(frozen=True)
class CodeSample:
    """The sampled context: files plus the budget accounting."""

    files: list[SampledFile] = field(default_factory=list)
    budget: int = 0
    skipped: list[str] = field(default_factory=list)  # "path — reason"

    @property
    def total_token_estimate(self) -> int:
        return sum(f.token_estimate for f in self.files)

    def to_manifest(self) -> dict:
        """Serializable summary WITHOUT file contents (they go to the
        prompt, never to an artifact)."""
        return {
            "budget": self.budget,
            "total_token_estimate": self.total_token_estimate,
            "files": [
                {
                    "path": f.path,
                    "size_bytes": f.size_bytes,
                    "reason": f.reason,
                    "token_estimate": f.token_estimate,
                }
                for f in self.files
            ],
            "skipped": self.skipped,
        }


FetchFn = Callable[[GitHubClient, RepoRef, str, str], str | None]


def sample_code(
    client: GitHubClient,
    ref: RepoRef,
    branch: str,
    facts: RepoFacts,
    *,
    budget: int,
    fetch_fn: FetchFn | None = None,
) -> CodeSample:
    """Select up to ``budget`` tokens of code worth showing the LLM.

    Priority: entry-point candidates (by confidence) → manifests →
    largest files. Vendored paths are excluded; files that fail to fetch
    are recorded in ``skipped``, not errors. Deterministic ordering makes
    the same repo + budget always produce the same sample.
    """
    fetch = fetch_fn or fetch_file_content
    candidates: list[tuple[str, str]] = []  # (path, reason)

    entrypoints = sorted(
        (c for c in facts.entrypoints if c.path),
        key=lambda c: c.confidence,
        reverse=True,
    )
    for c in entrypoints:
        assert c.path is not None  # filtered above
        candidates.append((c.path, f"entrypoint: {c.kind} ({c.confidence:.2f})"))

    for manifest in facts.manifests:
        candidates.append((manifest.path, f"manifest: {manifest.kind}"))

    for entry in facts.files.largest_files:
        candidates.append((entry.path, f"largest file ({entry.size_bytes} bytes)"))

    seen: set[str] = set()
    skipped: list[str] = []
    sampled: list[SampledFile] = []
    remaining = budget

    for path, reason in candidates:
        if path in seen or _is_vendored(path):
            continue
        seen.add(path)

        content = fetch(client, ref, branch, path)
        if content is None:
            skipped.append(f"{path} - fetch failed or file missing")
            continue

        tokens = max(1, len(content) // 4)
        if tokens > budget * MAX_SINGLE_FILE_BUDGET_SHARE:
            skipped.append(
                f"{path} - estimated {tokens} tokens exceeds "
                f"{int(budget * MAX_SINGLE_FILE_BUDGET_SHARE)} single-file cap"
            )
            continue
        if tokens > remaining:
            skipped.append(f"{path} - budget exhausted ({tokens} > {remaining} remaining)")
            continue

        sampled.append(
            SampledFile(
                path=path,
                size_bytes=len(content.encode("utf-8")),
                reason=reason,
                token_estimate=tokens,
                content=content,
            )
        )
        remaining -= tokens

    return CodeSample(files=sampled, budget=budget, skipped=skipped)


def _is_vendored(path: str) -> bool:
    head = path.split("/")[0]
    return any(head == prefix or path.startswith(prefix + "/") for prefix in VENDORED_PREFIXES)
