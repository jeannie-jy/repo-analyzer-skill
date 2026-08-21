"""Report schema: the single source of truth for the LLM's output shape.

The analysis JSON produced by the reasoning layer is validated against
:data:`REPORT_SCHEMA`, a JSON-schema (draft-07) document. The same dict is
exported to ``schemas/analysis_report.schema.json`` — one source, no drift
between code and artifact.

Validation is a hand-rolled subset of JSON-schema (``type``, ``required``,
``properties``, ``items``, ``enum``) — enough for this contract and zero
third-party dependencies. It returns a list of human-readable violations,
each with a JSON pointer, so a failing LLM output can be fixed
incrementally instead of being rejected wholesale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ReportValidationError

REPORT_SCHEMA_VERSION = "1.0"

# JSON-schema (draft-07) description of the LLM analysis output.
# `analysis_report.schema.json` is exported from this dict — edit here only.
REPORT_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "repo-analyzer analysis report",
    "type": "object",
    "required": [
        "overview",
        "tech_stack",
        "structure",
        "architecture",
        "core_modules",
        "entry_points",
        "execution_flow",
        "key_files",
        "dependencies",
        "risks",
        "reading_order",
        "contribution_opportunities",
        "unknowns",
    ],
    "properties": {
        "overview": {
            "type": "object",
            "required": ["summary", "purpose", "evidence"],
            "properties": {
                "summary": {"type": "string"},
                "purpose": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
        },
        "tech_stack": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "name", "role", "evidence"],
                "properties": {
                    "category": {"type": "string", "enum": ["language", "framework", "database", "tooling", "other"]},
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        },
        "structure": {
            "type": "object",
            "required": ["summary", "notable_dirs"],
            "properties": {
                "summary": {"type": "string"},
                "notable_dirs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path", "purpose", "evidence"],
                        "properties": {
                            "path": {"type": "string"},
                            "purpose": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        },
                    },
                },
            },
        },
        "architecture": {
            "type": "object",
            "required": ["summary", "layers", "data_flow", "patterns"],
            "properties": {
                "summary": {"type": "string"},
                "layers": {"type": "array", "items": {"type": "string"}},
                "data_flow": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["from", "to", "mechanism", "evidence"],
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "mechanism": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        },
                    },
                },
                "patterns": {"type": "array", "items": {"type": "string"}},
            },
        },
        "core_modules": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "path", "responsibility", "key_symbols", "relationships", "evidence"],
                "properties": {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "responsibility": {"type": "string"},
                    "key_symbols": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["symbol", "location"],
                            "properties": {
                                "symbol": {"type": "string"},
                                "location": {"type": "string"},
                            },
                        },
                    },
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["with", "mechanism", "evidence"],
                            "properties": {
                                "with": {"type": "string"},
                                "mechanism": {"type": "string"},
                                "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                            },
                        },
                    },
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        },
        "entry_points": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "kind", "invocation", "confidence", "rationale", "evidence"],
                "properties": {
                    "path": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["cli", "http_server", "worker", "library_api", "scheduler", "other"],
                    },
                    "invocation": {"type": "string"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        },
        "execution_flow": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step", "description", "evidence"],
                "properties": {
                    "step": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        },
        "key_files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "why", "evidence"],
                "properties": {
                    "path": {"type": "string"},
                    "why": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        },
        "dependencies": {
            "type": "object",
            "required": ["notable", "concerns"],
            "properties": {
                "notable": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "purpose", "evidence"],
                        "properties": {
                            "name": {"type": "string"},
                            "purpose": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        },
                    },
                },
                "concerns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["description", "evidence"],
                        "properties": {
                            "description": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        },
                    },
                },
            },
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "description", "severity", "evidence", "mitigation"],
                "properties": {
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "mitigation": {"type": "string"},
                },
            },
        },
        "reading_order": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step", "target", "why"],
                "properties": {
                    "step": {"type": "string"},
                    "target": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
        "contribution_opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["area", "description", "difficulty", "related_files", "evidence"],
                "properties": {
                    "area": {"type": "string"},
                    "description": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["low", "medium", "high"]},
                    "related_files": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
}

# JSON types -> Python types (bool must not pass as number).
_TYPE_CHECK: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_analysis(analysis: dict) -> ValidationResult:
    """Validate an LLM analysis dict against the report schema.

    Returns the full list of violations (each with a JSON pointer); the
    caller decides whether to fail or to proceed with warnings.
    """
    errors: list[str] = []
    _validate_node(analysis, REPORT_SCHEMA, "", errors)
    return ValidationResult(valid=not errors, errors=errors)


def assert_valid(analysis: dict) -> None:
    """Raise ``ReportValidationError`` (with all violations) when invalid."""
    result = validate_analysis(analysis)
    if not result.valid:
        raise ReportValidationError(
            "Analysis failed report schema validation:\n- "
            + "\n- ".join(result.errors)
        )


def export_schema(path: str | Path) -> Path:
    """Export :data:`REPORT_SCHEMA` to ``schemas/analysis_report.schema.json``.

    The exported file is derived from this module — edit the dict, never
    the artifact. Used by ``python -m repo_analyzer.report.schema``.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(REPORT_SCHEMA, indent=2), encoding="utf-8"
    )
    return target


def _validate_node(instance: Any, node_schema: dict, pointer: str, errors: list[str]) -> None:
    """Recursive validator for the JSON-schema subset we use."""
    if "enum" in node_schema:
        if instance not in node_schema["enum"]:
            errors.append(
                f"{pointer}: expected one of {node_schema['enum']}, got {instance!r}"
            )
            return  # enum implies type; stop after the clearer error

    schema_type = node_schema.get("type")
    if schema_type:
        expected = _TYPE_CHECK[schema_type]
        # bool is an int subclass; JSON-schema keeps them distinct
        if schema_type in ("number", "integer") and isinstance(instance, bool):
            errors.append(f"{pointer}: expected {schema_type}, got boolean ({instance!r})")
            return
        if not isinstance(instance, expected):
            errors.append(
                f"{pointer}: expected {schema_type}, got "
                f"{type(instance).__name__} ({instance!r})"
            )
            return  # no point checking structure of a wrong-typed node

    if schema_type == "object" and isinstance(instance, dict):
        for required in node_schema.get("required", []):
            if required not in instance:
                errors.append(f"{pointer}.{required}: missing required field")
        properties = node_schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate_node(value, properties[key], f"{pointer}.{key}", errors)

    elif schema_type == "array" and isinstance(instance, list):
        item_schema = node_schema.get("items", {})
        min_items = node_schema.get("minItems", 0)
        if len(instance) < min_items:
            errors.append(
                f"{pointer}: expected at least {min_items} item(s), got {len(instance)}"
            )
        for index, value in enumerate(instance):
            _validate_node(value, item_schema, f"{pointer}[{index}]", errors)


if __name__ == "__main__":  # python -m repo_analyzer.report.schema
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("schemas/analysis_report.schema.json")
    export_schema(target)
    print(f"Schema exported to {target}")
