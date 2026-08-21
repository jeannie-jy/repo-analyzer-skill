"""Report schema validation: contract enforcement on LLM output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_analyzer.errors import ReportValidationError
from repo_analyzer.report.schema import (
    REPORT_SCHEMA,
    assert_valid,
    export_schema,
    validate_analysis,
)

from .test_analyze_pipeline import VALID_ANALYSIS


def _deep_copy(data: dict) -> dict:
    return json.loads(json.dumps(data))


def test_valid_analysis_passes() -> None:
    result = validate_analysis(VALID_ANALYSIS)
    assert result.valid
    assert result.errors == []


def test_missing_top_level_section_fails() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    del broken["risks"]
    result = validate_analysis(broken)
    assert not result.valid
    assert any("risks" in e and "missing required" in e for e in result.errors)


def test_missing_nested_required_field_fails() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    del broken["overview"]["purpose"]
    result = validate_analysis(broken)
    assert not result.valid
    assert any("overview.purpose" in e for e in result.errors)


def test_wrong_type_fails() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    broken["overview"]["summary"] = 42
    result = validate_analysis(broken)
    assert not result.valid
    assert any("overview.summary" in e and "expected string" in e for e in result.errors)


def test_bool_is_not_a_number() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    broken["entry_points"][0]["confidence"] = True
    result = validate_analysis(broken)
    assert not result.valid
    assert any("expected number" in e and "boolean" in e for e in result.errors)


def test_invalid_enum_fails() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    broken["risks"][0]["severity"] = "critical"
    result = validate_analysis(broken)
    assert not result.valid
    assert any("critical" in e for e in result.errors)


def test_evidence_items_must_be_strings() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    broken["overview"]["evidence"] = ["README.md", 7]
    result = validate_analysis(broken)
    assert not result.valid
    assert any("overview.evidence[1]" in e for e in result.errors)


def test_empty_evidence_fails_min_items() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    broken["overview"]["evidence"] = []
    result = validate_analysis(broken)
    assert not result.valid
    assert any("at least 1 item" in e for e in result.errors)


def test_assert_valid_raises_with_all_violations() -> None:
    broken = _deep_copy(VALID_ANALYSIS)
    del broken["overview"]["purpose"]
    del broken["entry_points"]
    with pytest.raises(ReportValidationError) as exc_info:
        assert_valid(broken)
    message = str(exc_info.value)
    assert "overview.purpose" in message
    assert "entry_points" in message
    assert "- " in message  # one bullet per violation


def test_export_schema_writes_json(tmp_path) -> None:
    target = export_schema(tmp_path / "schema.json")
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert "properties" in data
    assert set(data["required"]) >= {
        "overview", "tech_stack", "structure", "architecture", "core_modules",
        "entry_points", "execution_flow", "key_files", "dependencies",
        "risks", "reading_order", "contribution_opportunities", "unknowns",
    }
    # the committed artifact is derived from the same dict (single source)
    committed = json.loads(
        (Path(__file__).parents[2] / "schemas" / "analysis_report.schema.json").read_text(encoding="utf-8")
    )
    assert committed == REPORT_SCHEMA
