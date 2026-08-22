"""Content that should never be fed to an LLM or counted as code.

Kept in its own module (not tree.py) because the local snapshot layer
also filters on it — a shared definition that tree.py re-exports keeps
every consumer (file stats, languages, code sampling, local snapshots)
consistent.
"""

from __future__ import annotations

from pathlib import Path

# Binary formats (decoding them produces garbage text) and lockfiles
# (generated, huge, zero architectural signal).
BINARY_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".tar", ".7z",
        ".exe", ".dll", ".so", ".dylib", ".pyc", ".class", ".jar", ".war",
        ".o", ".a", ".bin", ".dat", ".db", ".sqlite", ".parquet",
    }
)
LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
        "pnpm-lock.yaml", "uv.lock", "poetry.lock", "Pipfile.lock",
        "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "mix.lock",
    }
)


def is_binary_or_lockfile(path: str) -> bool:
    """True for binary formats and lockfiles — never LLM- or LOC-material."""
    if Path(path).name in LOCKFILE_NAMES:
        return True
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


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
