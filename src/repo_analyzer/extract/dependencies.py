"""Manifest detection + dependency extraction.

Supports the formats the stdlib can parse honestly: JSON (npm/composer),
TOML via ``tomllib`` (pyproject/Pipfile/Cargo), line-based text
(requirements.txt/Gemfile), plus small regex parsers for go.mod, setup.py
and pubspec.yaml. Anything else lands in ``unparseable`` with a reason —
we prefer an honest miss over a wrong parse.

Note: this module fetches manifest contents itself; entrypoints.py fetches
a few of the same files again (package.json, pyproject.toml, Dockerfile).
Keeping the modules independent is deliberate — the duplicate requests are
cheap and the modules stay individually testable.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from dataclasses import dataclass

from ..github_client import GitHubClient, fetch_file_content
from ..models import (
    Dependency,
    Dependencies,
    ManifestInfo,
    RepoRef,
    RepoTree,
    TreeEntry,
    UnparseableManifest,
)

MAX_MANIFESTS = 20

# (glob pattern, kind, format) — matched against blob paths via fnmatch
MANIFEST_RULES: tuple[tuple[str, str, str], ...] = (
    ("package.json", "npm", "json"),
    ("composer.json", "composer", "json"),
    ("pyproject.toml", "pyproject", "toml"),
    ("Pipfile", "pipenv", "toml"),
    ("Cargo.toml", "cargo", "toml"),
    ("requirements.txt", "pip", "text"),
    ("requirements-*.txt", "pip", "text"),
    ("Gemfile", "bundler", "text"),
    ("go.mod", "go", "regex"),
    ("setup.py", "setuptools", "regex"),
    ("pubspec.yaml", "dart", "yaml"),
)

_PEP508_ITEM = re.compile(r"^([A-Za-z0-9_.-]+)\s*(.*)$")
_REQ_LINE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*([<>=!~].*)?$")
_GO_SINGLE = re.compile(r"require\s+([^\s]+)\s+(v[\w.+-]+)")
_GO_BLOCK = re.compile(r"^\s*([^\s/]+\.[^\s/]+/[^\s]+)\s+(v[\w.+-]+)\s*$", re.M)
_SETUP_DEPS = re.compile(r"install_requires\s*=\s*\[([^\]]*)\]", re.S)
_SETUP_ITEM = re.compile(r"""['"]([A-Za-z0-9_.\-]+)['"]""")
_YAML_ITEM = re.compile(r"^\s{2}([a-z0-9_]+):\s*(.*)$", re.M)


@dataclass(frozen=True)
class ManifestRule:
    pattern: str
    kind: str
    format: str


def detect_manifests(tree: RepoTree) -> list[ManifestInfo]:
    """Find manifest files in the tree (cap ``MAX_MANIFESTS``).

    Rules match both the repo root and any subdirectory (monorepos), so
    ``requirements.txt`` matches ``src/requirements.txt``.
    """
    found: list[ManifestInfo] = []
    for entry in tree.entries:
        if entry.type != "blob":
            continue
        for pattern, kind, fmt in MANIFEST_RULES:
            if _matches_manifest(entry.path, pattern):
                found.append(ManifestInfo(path=entry.path, kind=kind, format=fmt))
                break
        if len(found) >= MAX_MANIFESTS:
            break
    return found


def _matches_manifest(path: str, pattern: str) -> bool:
    """Exact/root match or anywhere in the tree (``*/pattern``)."""
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"*/{pattern}")


def extract_dependencies(
    client: GitHubClient,
    ref: RepoRef,
    branch: str,
    tree: RepoTree,
) -> Dependencies:
    """Fetch and parse every detected manifest."""
    direct: list[Dependency] = []
    unparseable: list[UnparseableManifest] = []
    for manifest in detect_manifests(tree):
        content = fetch_file_content(client, ref, branch, manifest.path)
        if content is None:
            unparseable.append(
                UnparseableManifest(
                    path=manifest.path,
                    reason="file missing, too large, or not text",
                )
            )
            continue
        try:
            direct.extend(_parse_manifest(content, manifest))
        except (ValueError, tomllib.TOMLDecodeError) as exc:
            unparseable.append(
                UnparseableManifest(path=manifest.path, reason=str(exc))
            )
    return Dependencies(direct=direct, unparseable=unparseable)


# ---------------------------------------------------------------------------
# Per-format parsers — each is a pure function (content, manifest) -> deps
# ---------------------------------------------------------------------------


def _parse_manifest(content: str, manifest: ManifestInfo) -> list[Dependency]:
    if manifest.format == "json":
        return _parse_json(content, manifest)
    if manifest.format == "toml":
        return _parse_toml(content, manifest)
    if manifest.format == "text":
        return _parse_text(content, manifest)
    if manifest.format == "regex":
        if manifest.kind == "go":
            return _parse_go(content, manifest)
        if manifest.kind == "setuptools":
            return _parse_setup_py(content, manifest)
        raise ValueError(f"unsupported regex kind: {manifest.kind}")
    if manifest.format == "yaml":
        return _parse_yaml(content, manifest)
    raise ValueError(f"unsupported format: {manifest.format}")


def _parse_json(content: str, manifest: ManifestInfo) -> list[Dependency]:
    data = json.loads(content)
    deps: list[Dependency] = []
    for category, key in (
        ("runtime", "dependencies"),
        ("dev", "devDependencies"),
        ("runtime", "peerDependencies"),
    ):
        section = data.get(key) or {}
        for name, version in section.items():
            deps.append(
                Dependency(
                    name=name,
                    version=str(version),
                    manifest=manifest.path,
                    category=category,
                )
            )
    return deps


def _parse_toml(content: str, manifest: ManifestInfo) -> list[Dependency]:
    data = tomllib.loads(content)
    deps: list[Dependency] = []

    # PEP 621: [project].dependencies
    project = data.get("project") or {}
    for spec in project.get("dependencies") or []:
        name, version = _split_pep508(str(spec))
        if name:
            deps.append(
                Dependency(name=name, version=version, manifest=manifest.path)
            )
    # Poetry: [tool.poetry.dependencies] / [tool.poetry.group.dev.dependencies]
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name, version in (poetry.get("dependencies") or {}).items():
        if name == "python":
            continue
        deps.append(
            Dependency(
                name=name,
                version=_coerce_version(version),
                manifest=manifest.path,
                category="runtime",
            )
        )
    poetry_dev = (poetry.get("group") or {}).get("dev") or {}
    for name, version in (poetry_dev.get("dependencies") or {}).items():
        deps.append(
            Dependency(
                name=name,
                version=_coerce_version(version),
                manifest=manifest.path,
                category="dev",
            )
        )
    # Cargo: [dependencies] / [dev-dependencies] / [build-dependencies]
    for category, key in (
        ("runtime", "dependencies"),
        ("dev", "dev-dependencies"),
        ("runtime", "build-dependencies"),
    ):
        section = data.get(key) or {}
        for name, version in section.items():
            deps.append(
                Dependency(
                    name=name,
                    version=_coerce_version(version),
                    manifest=manifest.path,
                    category=category,
                )
            )
    # Pipenv: [packages] / [dev-packages]
    for category, key in (("runtime", "packages"), ("dev", "dev-packages")):
        section = data.get(key) or {}
        for name, version in section.items():
            deps.append(
                Dependency(
                    name=name,
                    version=_coerce_version(version),
                    manifest=manifest.path,
                    category=category,
                )
            )
    return deps


def _split_pep508(spec: str) -> tuple[str | None, str | None]:
    match = _PEP508_ITEM.match(spec.strip())
    if not match:
        return None, None
    return match.group(1), match.group(2).strip() or None


def _coerce_version(version: object) -> str | None:
    """Version values may be str, dict (poetry style), or None."""
    if isinstance(version, str):
        return version or None
    if isinstance(version, dict):
        return str(version.get("version") or "")
    return str(version) if version is not None else None


def _parse_text(content: str, manifest: ManifestInfo) -> list[Dependency]:
    deps: list[Dependency] = []
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(("-r", "-e", "--", "git+", "http")):
            continue
        match = _REQ_LINE.match(line)
        if match:
            deps.append(
                Dependency(
                    name=match.group(1),
                    version=match.group(2),
                    manifest=manifest.path,
                )
            )
    return deps


def _parse_go(content: str, manifest: ManifestInfo) -> list[Dependency]:
    deps: list[Dependency] = []
    for name, version in _GO_SINGLE.findall(content):
        deps.append(Dependency(name=name, version=version, manifest=manifest.path))
    for name, version in _GO_BLOCK.findall(content):
        deps.append(Dependency(name=name, version=version, manifest=manifest.path))
    return deps


def _parse_setup_py(content: str, manifest: ManifestInfo) -> list[Dependency]:
    match = _SETUP_DEPS.search(content)
    if not match:
        return []
    names = [name for name in _SETUP_ITEM.findall(match.group(1))]
    return [
        Dependency(name=name, version=None, manifest=manifest.path) for name in names
    ]


def _parse_yaml(content: str, manifest: ManifestInfo) -> list[Dependency]:
    """Best-effort regex YAML for pubspec.yaml-style files."""
    deps: list[Dependency] = []
    in_dependencies = False
    for line in content.splitlines():
        if line == "dependencies:":
            in_dependencies = True
            continue
        if in_dependencies and line and not line.startswith((" ", "\t")):
            in_dependencies = False
        if not in_dependencies:
            continue
        match = _YAML_ITEM.match(line)
        if match and not match.group(1).startswith(("#", "flutter", "sdk")):
            deps.append(
                Dependency(
                    name=match.group(1),
                    version=match.group(2).strip() or None,
                    manifest=manifest.path,
                )
            )
    return deps
