"""Deterministic citation checking — the hallucination gate.

Every claim in the analysis carries an ``evidence`` array of file paths.
This module walks the whole analysis document, collects every path claim,
and verifies each one against the real repository tree. The result makes
grounding measurable: ``verified / total`` is the report's grounding
score, and ``unverified_list`` is exactly what an agent must fix before
the report is trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import RepoTree

# Keys whose values are arrays of file paths.
_PATH_KEYS = ("evidence", "related_files")


@dataclass(frozen=True)
class EvidenceReport:
    total_citations: int
    verified: int
    unverified: int
    unverified_list: list[str] = field(default_factory=list)

    @property
    def grounding_ratio(self) -> float:
        if self.total_citations == 0:
            return 0.0
        return self.verified / self.total_citations

    def to_dict(self) -> dict:
        return {
            "total_citations": self.total_citations,
            "verified": self.verified,
            "unverified": self.unverified,
            "unverified_list": self.unverified_list,
        }


def verify_evidence(analysis: dict, tree: RepoTree) -> EvidenceReport:
    """Verify every path claim in the analysis against the tree.

    Paths are deduplicated for counting (a heavily cited file is one
    citation, not ten); every distinct path either exists in the tree
    (``verified``) or not (``unverified``, listed for fixing).
    """
    tree_paths = {entry.path for entry in tree.entries}
    citations = _collect_paths(analysis)
    verified = [p for p in citations if p in tree_paths]
    unverified = [p for p in citations if p not in tree_paths]
    return EvidenceReport(
        total_citations=len(citations),
        verified=len(verified),
        unverified=len(unverified),
        unverified_list=sorted(unverified),
    )


def _collect_paths(node: Any) -> list[str]:
    """Recursively collect string values under the ``_PATH_KEYS`` keys."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _PATH_KEYS and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item:
                        found.append(item)
            else:
                found.extend(_collect_paths(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_paths(item))
    return sorted(set(found))
