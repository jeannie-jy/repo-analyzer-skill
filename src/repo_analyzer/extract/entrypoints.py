"""Heuristic entry-point detection.

Deterministic candidates only — the LLM reasoning layer re-ranks them
later and explains *which* ones matter. Every candidate carries:

- ``path``: the file that actually starts something when available (the
  heuristic is verified against the tree), else the manifest that
  declares it
- ``heuristic``: exactly what rule matched, so the claim is auditable
- ``confidence``: from the rule alone, before any LLM judgment
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib

from ..github_client import GitHubClient, fetch_file_content
from ..models import EntrypointCandidate, RepoRef, RepoTree

# --- file-presence rules: (glob, kind, confidence, description) ------------
_FILE_RULES: tuple[tuple[str, str, float, str], ...] = (
    ("**/__main__.py", "library_entry", 0.75, "python package __main__"),
    ("**/manage.py", "cli", 0.90, "Django management CLI"),
    ("**/wsgi.py", "http_server", 0.65, "WSGI entry point"),
    ("**/asgi.py", "http_server", 0.65, "ASGI entry point"),
    ("**/main.py", "entrypoint_script", 0.40, "main.py present"),
    ("**/app.py", "http_server", 0.50, "app.py (typical WSGI/ASGI app)"),
    ("**/main.go", "entrypoint_script", 0.55, "Go main package"),
    ("Dockerfile", "container_entry", 0.50, "Dockerfile present"),
    ("**/Dockerfile", "container_entry", 0.50, "Dockerfile present"),
    ("Makefile", "build_entry", 0.50, "Makefile present"),
)

_MAKEFILE_TARGET = re.compile(r"^(\.PHONY|run|start|dev|serve|test):", re.M)
_DOCKERFILE_ENTRY = re.compile(r"^(CMD|ENTRYPOINT)\s+(.+)$", re.M)

# --- library package root: the import surface is the entry ------------------
_LIBRARY_EXCLUDED_DIRS = {
    "tests", "test", "docs", "example", "examples",
    "benchmark", "benchmarks", "demo", "demos",
    "scripts", "playground", "site", "src",   # "src" is a layout marker, not a package
}
_LIBRARY_MIN_PY_FILES = 2


def _library_package_root(paths: set[str]) -> tuple[str, str] | None:
    """Strongest package root as (init_path, package_name), else None.

    Only <pkg>/__init__.py (top-level, 2 segments) or src/<pkg>/__init__.py
    (src-layout, 3 segments) count as roots — nested packages never do.
    Excluded dir names never are roots. A root must contain >= 2 .py files
    (init plus code) to kill stub/empty packages. Deterministic: src-layout
    wins over top-level (tier), then most .py files, then lexicographically
    largest name — explicit max() tuple, never set-iteration order.
    """
    roots: list[tuple[int, int, str, str, str]] = []
    for path in paths:
        if not path.endswith("__init__.py"):
            continue
        parts = path.split("/")
        if len(parts) == 2:
            pkg_dir, tier = parts[0], 0
        elif len(parts) == 3 and parts[0] == "src":
            pkg_dir, tier = parts[1], 1
        else:
            continue
        if pkg_dir in _LIBRARY_EXCLUDED_DIRS:
            continue
        prefix = f"src/{pkg_dir}" if tier else pkg_dir
        py_count = sum(1 for p in paths if p.startswith(prefix + "/") and p.endswith(".py"))
        if py_count < _LIBRARY_MIN_PY_FILES:
            continue
        roots.append((tier, py_count, pkg_dir, path, pkg_dir))
    if not roots:
        return None
    _, _, _, init_path, pkg_name = max(roots)
    return init_path, pkg_name


def extract_entrypoints(
    client: GitHubClient,
    ref: RepoRef,
    branch: str,
    tree: RepoTree,
) -> list[EntrypointCandidate]:
    """Produce deterministic entry-point candidates from the tree + a few
    manifest contents. Never raises for missing files — a missing file is
    just "no candidate from that rule"."""
    candidates: list[EntrypointCandidate] = []
    seen: set[tuple[str | None, str]] = set()

    def add(candidate: EntrypointCandidate) -> None:
        """Dedupe by (path, kind); a stronger rule replaces a weaker one.

        Example: ``Dockerfile`` present (0.5) then ``CMD`` found (0.8) —
        the content rule carries more evidence, so it wins.
        """
        key = (candidate.path, candidate.kind)
        if key in seen:
            for i, existing in enumerate(candidates):
                if (existing.path, existing.kind) == key and existing.confidence < candidate.confidence:
                    candidates[i] = candidate
            return
        seen.add(key)
        candidates.append(candidate)

    paths = {e.path for e in tree.entries}

    # 1. file-presence rules -------------------------------------------------
    for glob, kind, confidence, description in _FILE_RULES:
        for path in paths:
            if _matches(path, glob):
                add(
                    EntrypointCandidate(
                        path=path,
                        kind=kind,
                        heuristic=description,
                        confidence=confidence,
                    )
                )

    # 2. package.json: bin / scripts ----------------------------------------
    pkg_content = fetch_file_content(client, ref, branch, "package.json")
    if pkg_content is not None:
        try:
            pkg = json.loads(pkg_content)
        except json.JSONDecodeError:
            pkg = {}
        bin_spec = pkg.get("bin")
        if isinstance(bin_spec, str):
            _add_bin(candidates, add, paths, bin_spec, "package.json")
        elif isinstance(bin_spec, dict):
            for _name, target in bin_spec.items():
                _add_bin(candidates, add, paths, target, "package.json")
        for script_name, script in (pkg.get("scripts") or {}).items():
            kind = _script_kind(script_name)
            if kind:
                add(
                    EntrypointCandidate(
                        path="package.json",
                        kind=kind,
                        heuristic=f"npm script '{script_name}'",
                        confidence=0.60,
                        invocation=f"npm run {script_name}",
                    )
                )

    # 3. pyproject.toml: [project].scripts ------------------------------------
    pyproject_content = fetch_file_content(client, ref, branch, "pyproject.toml")
    if pyproject_content is not None:
        try:
            pyproject = tomllib.loads(pyproject_content)
        except tomllib.TOMLDecodeError:
            pyproject = {}
        scripts = (pyproject.get("project") or {}).get("scripts") or {}
        for name, target in scripts.items():
            add(
                EntrypointCandidate(
                    path="pyproject.toml",
                    kind="cli",
                    heuristic=f"PEP 621 [project].scripts entry '{name}'",
                    confidence=0.95,
                    invocation=f"{name} -> {target}",
                )
            )

    # 4. Dockerfile: CMD / ENTRYPOINT -----------------------------------------
    dockerfile = fetch_file_content(client, ref, branch, "Dockerfile")
    if dockerfile is not None:
        for match in _DOCKERFILE_ENTRY.finditer(dockerfile):
            add(
                EntrypointCandidate(
                    path="Dockerfile",
                    kind="container_entry",
                    heuristic=f"Dockerfile {match.group(1)} directive",
                    confidence=0.80,
                    invocation=match.group(2).strip(),
                )
            )

    # 5. Makefile: dev/build targets -------------------------------------------
    makefile = fetch_file_content(client, ref, branch, "Makefile")
    if makefile is not None and _MAKEFILE_TARGET.search(makefile):
        add(
            EntrypointCandidate(
                path="Makefile",
                kind="build_entry",
                heuristic="Makefile with run/dev/test targets",
                confidence=0.60,
                invocation="make run (typical)",
            )
        )

    # 6. library package root: a pure library's entry is its import surface.
    #    Skip when a real runnable entry exists (cli/http_server); build/CI
    #    artifacts (Makefile, Dockerfile) must NOT suppress it.
    if not any(c.kind in ("cli", "http_server") for c in candidates):
        root = _library_package_root(paths)
        if root is not None:
            init_path, pkg_name = root
            add(EntrypointCandidate(
                path=init_path,
                kind="library_api",
                heuristic="library package root (import surface)",
                confidence=0.40,
                invocation=f"import {pkg_name.replace('-', '_')}",
            ))

    return candidates


def _matches(path: str, glob: str) -> bool:
    """fnmatch, with ``**/x`` also matching a root-level ``x``."""
    if fnmatch.fnmatch(path, glob):
        return True
    return glob.startswith("**/") and fnmatch.fnmatch(path, glob[3:])


def _add_bin(
    candidates: list[EntrypointCandidate],
    add,
    paths: set[str],
    target: str,
    manifest_path: str,
) -> None:
    """A bin target whose file exists in the tree is stronger evidence."""
    in_tree = target in paths
    add(
        EntrypointCandidate(
            path=target if in_tree else manifest_path,
            kind="cli",
            heuristic=f"package.json bin -> {target}"
            + ("" if in_tree else " (file not in tree)"),
            confidence=0.95 if in_tree else 0.85,
            invocation=target,
        )
    )


def _script_kind(script_name: str) -> str | None:
    normalized = script_name.lower()
    if normalized in ("start", "serve", "server", "run", "dev"):
        return "http_server"
    if normalized in ("build", "compile"):
        return "build_entry"
    if normalized in ("test", "lint", "check"):
        return None  # quality gates, not entry points
    return None
