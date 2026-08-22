"""Orchestrate the deterministic extraction layer into ``repo_facts.json``.

Failure semantics (see docs/ARCHITECTURE.md §9):

- Metadata resolution is the root dependency — if it fails, everything
  downstream is meaningless, so we raise ``ExtractionError``.
- Every other module fails independently: its failure lands in
  ``warnings`` and the corresponding fact section stays at its defaults
  (or is skipped entirely when it depends on the tree).
- The result is always a complete, schema-valid ``RepoFacts`` document.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..errors import ExtractionError, RepoAnalyzerError
from ..extract.local import head_sha_local, is_git_repo
from ..github_client import GitHubClient
from ..models import (
    FACTS_FILENAME,
    FACTS_SCHEMA_VERSION,
    Dependencies,
    FileStats,
    GitStats,
    LanguageStats,
    ReadmeInfo,
    RepoFacts,
    RepoRef,
    RepoTree,
    TOOL_NAME,
)
from ..extract import (
    dependencies as deps_module,
    entrypoints as entrypoints_module,
    file_stats as file_stats_module,
    git_stats as git_stats_module,
    languages as languages_module,
    metadata as metadata_module,
    readme as readme_module,
    tree as tree_module,
)

_EMPTY_TREE = RepoTree()
_EMPTY_DEPENDENCIES = Dependencies()
_EMPTY_FILES = FileStats()
_EMPTY_GIT = GitStats()
_EMPTY_LANGUAGES = LanguageStats()
_EMPTY_README = ReadmeInfo()


def extract_facts(
    client: GitHubClient,
    ref: RepoRef,
    *,
    output_dir: str | Path,
    fetch_raw_fn: Callable[[RepoRef, str, str], str] | None = None,
) -> RepoFacts:
    """Run the full deterministic extraction and write ``repo_facts.json``.

    ``fetch_raw_fn`` is injected into the file-stats module so tests can
    stub raw.githubusercontent.com fetches (default: real raw fetches).

    Returns the facts (already written to disk) for direct use.
    """
    warnings: list[str] = []

    # --- root dependency: metadata + branch resolution ----------------------
    try:
        metadata = metadata_module.extract_metadata(client, ref)
    except RepoAnalyzerError as exc:
        raise ExtractionError(
            f"Could not resolve repository metadata for {ref.api_path}: {exc}"
        ) from exc

    branch = ref.ref or metadata.default_branch

    # --- head sha (for reproducible artifact identity) ----------------------
    ref_sha: str | None = None
    if ref.local_path is not None:
        ref_sha = head_sha_local(ref.local_path)
        if ref_sha is None:
            warnings.append(
                "Could not resolve head sha for local path (not a git repository)"
            )
    else:
        try:
            head = client.get_json(
                f"repos/{ref.api_path}/commits",
                params={"per_page": 1, "sha": branch},
            )
            if head:
                ref_sha = head[0].get("sha")
        except RepoAnalyzerError as exc:
            warnings.append(f"Could not resolve head sha for {branch}: {exc}")

    # --- independent facts ---------------------------------------------------
    tree: RepoTree = _EMPTY_TREE
    try:
        tree = tree_module.extract_tree(client, ref, branch)
    except RepoAnalyzerError as exc:
        warnings.append(f"Directory tree extraction failed: {exc}")

    languages: LanguageStats = _EMPTY_LANGUAGES
    try:
        languages = languages_module.extract_languages(client, ref)
    except RepoAnalyzerError as exc:
        warnings.append(f"Language statistics failed: {exc}")

    git: GitStats = _EMPTY_GIT
    try:
        git = git_stats_module.extract_git_stats(client, ref, branch)
    except RepoAnalyzerError as exc:
        warnings.append(f"Git statistics failed: {exc}")

    # --- tree-dependent facts (skipped cleanly when the tree is empty) -------
    manifests: list = []
    dependencies: Dependencies = _EMPTY_DEPENDENCIES
    entrypoints: list = []
    files: FileStats = _EMPTY_FILES

    if tree.entries:
        try:
            dependencies = deps_module.extract_dependencies(client, ref, branch, tree)
            manifests = deps_module.detect_manifests(tree)
        except RepoAnalyzerError as exc:
            warnings.append(f"Dependency extraction failed: {exc}")

        try:
            entrypoints = entrypoints_module.extract_entrypoints(
                client, ref, branch, tree
            )
        except RepoAnalyzerError as exc:
            warnings.append(f"Entry-point detection failed: {exc}")

        try:
            files = file_stats_module.extract_file_stats(
                client, ref, branch, tree, fetch_raw_fn=fetch_raw_fn
            )
        except RepoAnalyzerError as exc:
            warnings.append(f"File statistics failed: {exc}")

    readme: ReadmeInfo = _EMPTY_README
    try:
        readme = readme_module.extract_readme(client, ref, branch)
    except RepoAnalyzerError as exc:
        warnings.append(f"README extraction failed: {exc}")

    if ref.local_path is not None:
        warnings.append(
            "local mode: metadata is minimal (no stars/issues); "
            "language shares are extension-based approximations"
        )
        if not is_git_repo(ref.local_path):
            warnings.append(
                "local mode: not a git repository - using a filesystem "
                "snapshot (untracked files included)"
            )
        elif not tree.entries and any(ref.local_path.iterdir()):
            warnings.append(
                "local mode: no tracked files found (untracked-only repo?)"
            )

    facts = RepoFacts(
        repo={
            "owner": ref.owner,
            "repo": ref.repo,
            "url": ref.url,
            "ref": ref.ref,
            "branch": branch,
            "ref_sha": ref_sha,
            "default_branch": metadata.default_branch,
        },
        metadata=metadata,
        tree=tree,
        languages=languages,
        manifests=manifests,
        dependencies=dependencies,
        entrypoints=entrypoints,
        git=git,
        files=files,
        readme=readme,
        warnings=warnings,
        source={
            "tool": TOOL_NAME,
            "version": __version__,
            "schema_version": FACTS_SCHEMA_VERSION,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    _write_facts(facts, ref.workdir(output_dir))
    return facts


def _write_facts(facts: RepoFacts, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / FACTS_FILENAME
    path.write_text(json.dumps(facts.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
