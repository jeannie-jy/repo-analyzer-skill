"""Full analyze pipeline: extract -> sample -> LLM -> artifacts on disk."""

from __future__ import annotations

import json

import pytest

from repo_analyzer.errors import LLMError, ReportValidationError
from repo_analyzer.models import (
    ANALYSIS_FILENAME,
    REPORT_FILENAME,
    REPORT_MD_FILENAME,
    SAMPLE_MANIFEST_FILENAME,
)
from repo_analyzer.pipeline.analyze import analyze, _parse_json_response

from .fake_client import FakeClient, contents_response
from .fake_llm import FakeLLM
from .test_facts_pipeline import REF, _full_client, _noop_raw

SAMPLE_CODE = (
    "from flask import Flask\n\napp = Flask(__name__)\n\n"
    "@app.route('/')\ndef index():\n    return 'hello'\n"
)

VALID_ANALYSIS = {
    "overview": {
        "summary": "A micro web framework",
        "purpose": "Building web apps",
        "evidence": ["README.md"],
    },
    "tech_stack": [{"category": "framework", "name": "Flask", "role": "web layer", "evidence": ["src/flask/app.py"]}],
    "structure": {
        "summary": "src layout",
        "notable_dirs": [{"path": "src/flask", "purpose": "core package", "evidence": ["src/flask/app.py"]}],
    },
    "architecture": {
        "summary": "WSGI app with routing",
        "layers": ["application", "routing"],
        "data_flow": [{"from": "client", "to": "app", "mechanism": "HTTP", "evidence": ["src/flask/app.py"]}],
        "patterns": ["factory"],
    },
    "core_modules": [
        {
            "name": "App",
            "path": "src/flask/app.py",
            "responsibility": "core object",
            "key_symbols": [{"symbol": "Flask", "location": "src/flask/app.py"}],
            "relationships": [{"with": "wrappers", "mechanism": "import", "evidence": ["src/flask/wrappers.py"]}],
            "evidence": ["src/flask/app.py"],
        }
    ],
    "entry_points": [
        {
            "path": "pyproject.toml",
            "kind": "cli",
            "invocation": "flask",
            "confidence": 0.95,
            "rationale": "PEP 621 entry",
            "evidence": ["pyproject.toml"],
        }
    ],
    "execution_flow": [{"step": "1", "description": "start server", "evidence": ["src/flask/app.py"]}],
    "key_files": [{"path": "src/flask/app.py", "why": "core", "evidence": ["src/flask/app.py"]}],
    "dependencies": {
        "notable": [{"name": "Werkzeug", "purpose": "WSGI", "evidence": ["pyproject.toml"]}],
        "concerns": [{"description": "old pins", "evidence": ["requirements.txt"]}],
    },
    "risks": [{"category": "complexity", "description": "x", "severity": "low", "evidence": ["src/flask/app.py"], "mitigation": "y"}],
    "reading_order": [{"step": "1", "target": "src/flask/app.py", "why": "core first"}],
    "contribution_opportunities": [
        {"area": "tests", "description": "more tests", "difficulty": "low", "related_files": ["tests/test_app.py"], "evidence": ["tests/test_app.py"]}
    ],
    "unknowns": ["CI behavior"],
}


def _client_with_app() -> FakeClient:
    return _full_client().route(
        "repos/pallets/flask/contents/src/flask/app.py",
        contents_response(SAMPLE_CODE, "src/flask/app.py"),
    )


def _run_analyze(tmp_path, response: str | Exception):
    llm = FakeLLM([response])
    result = analyze(
        _client_with_app(),
        llm,
        REF,
        output_dir=tmp_path,
        budget=40_000,
        fetch_raw_fn=_noop_raw,
    )
    return result, llm


def _run_analyze_repair(tmp_path, responses: list[str | Exception]):
    llm = FakeLLM(responses)
    result = analyze(
        _client_with_app(),
        llm,
        REF,
        output_dir=tmp_path,
        budget=40_000,
        fetch_raw_fn=_noop_raw,
    )
    return result, llm


def test_analyze_writes_artifacts(tmp_path) -> None:
    result, llm = _run_analyze(tmp_path, json.dumps(VALID_ANALYSIS))

    assert result.analysis == VALID_ANALYSIS
    assert result.model == "fake-model"
    assert result.schema_version == "1.0"
    assert result.repo["branch"] == "main"

    # the LLM was handed facts + sample in a two-message conversation
    assert len(llm.calls) == 1
    assert [m["role"] for m in llm.calls[0]] == ["system", "user"]
    assert "Werkzeug" in llm.calls[0][1]["content"]

    workdir = tmp_path / "repos" / "pallets" / "flask"
    analysis_path = workdir / ANALYSIS_FILENAME
    manifest_path = workdir / SAMPLE_MANIFEST_FILENAME
    assert analysis_path.exists()
    assert manifest_path.exists()

    on_disk = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert on_disk["analysis"] == VALID_ANALYSIS
    assert on_disk["sample_manifest"]["files"][0]["path"] == "pyproject.toml"
    # sample contents go to the prompt, never to disk
    assert all("content" not in f for f in on_disk["sample_manifest"]["files"])

    # report.json + report.md are the validated artifacts
    report_path = workdir / REPORT_FILENAME
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["analysis"] == VALID_ANALYSIS
    assert report["evidence_summary"]["verified"] >= 1
    assert report["evidence_summary"]["total_citations"] >= 1
    md = (workdir / REPORT_MD_FILENAME).read_text(encoding="utf-8")
    assert "Repository Analysis Report" in md
    assert "## Risks" in md
    # the deterministic digest annex survives the disk round-trip and renders
    assert report["digest_facts"]["git"]["commits_last_30d"] == 3
    assert "## Verified Facts (pipeline-computed)" in md


def test_analyze_language_flows_through(tmp_path) -> None:
    llm = FakeLLM([json.dumps(VALID_ANALYSIS)])
    result = analyze(
        _client_with_app(),
        llm,
        REF,
        output_dir=tmp_path,
        budget=40_000,
        fetch_raw_fn=_noop_raw,
        language="zh",
    )
    assert result.report["language"] == "zh"
    # the zh directive reached the LLM's system message
    assert "LANGUAGE:" in llm.calls[0][0]["content"]
    # report.json records the language; report.md renders zh labels
    workdir = tmp_path / "repos" / "pallets" / "flask"
    on_disk = json.loads((workdir / REPORT_FILENAME).read_text(encoding="utf-8"))
    assert on_disk["language"] == "zh"
    assert on_disk["digest_facts"] is not None  # annex survives the round-trip
    md = (workdir / REPORT_MD_FILENAME).read_text(encoding="utf-8")
    assert "# 仓库分析报告: pallets/flask" in md
    assert "## 概述" in md


def test_analyze_default_language_is_en(tmp_path) -> None:
    result, _ = _run_analyze(tmp_path, json.dumps(VALID_ANALYSIS))
    assert result.report["language"] == "en"


def test_analyze_tolerates_fenced_json(tmp_path) -> None:
    fenced = f"```json\n{json.dumps(VALID_ANALYSIS)}\n```"
    result, _ = _run_analyze(tmp_path, fenced)
    assert result.analysis == VALID_ANALYSIS


def test_analyze_tolerates_prose_around_json(tmp_path) -> None:
    result, _ = _run_analyze(tmp_path, f"Here you go:\n{json.dumps(VALID_ANALYSIS)}")
    assert result.analysis == VALID_ANALYSIS


def test_analyze_rejects_non_json(tmp_path) -> None:
    with pytest.raises(LLMError, match="no JSON"):
        _run_analyze(tmp_path, "I cannot analyze this repository.")


def test_analyze_retries_malformed_json_then_succeeds(tmp_path) -> None:
    # provider truncates the reply twice, then answers cleanly: the
    # identical call is retried instead of failing the pipeline
    truncated = '{"overview": {"summary": "cut off mid-'
    result, llm = _run_analyze_repair(
        tmp_path, [truncated, truncated, json.dumps(VALID_ANALYSIS)]
    )
    assert result.analysis == VALID_ANALYSIS
    assert len(llm.calls) == 3
    # every retry re-sent the same two-message prompt
    assert [m["role"] for m in llm.calls[1]] == ["system", "user"]


def test_analyze_gives_up_after_parse_retries(tmp_path) -> None:
    garbage = "not json at all"
    llm = FakeLLM([garbage, garbage, garbage])
    with pytest.raises(LLMError, match="no JSON"):
        analyze(
            _client_with_app(),
            llm,
            REF,
            output_dir=tmp_path,
            budget=40_000,
            fetch_raw_fn=_noop_raw,
        )
    assert len(llm.calls) == 3


def test_analyze_retries_repair_round_too(tmp_path) -> None:
    # the repair call can be truncated as well — same bounded retry
    broken = {k: v for k, v in VALID_ANALYSIS.items() if k != "risks"}
    truncated_repair = '{"risks": [{"category": "complexity", "de'
    llm = FakeLLM([json.dumps(broken), truncated_repair, json.dumps(VALID_ANALYSIS)])
    result = analyze(
        _client_with_app(),
        llm,
        REF,
        output_dir=tmp_path,
        budget=40_000,
        fetch_raw_fn=_noop_raw,
    )
    assert result.analysis == VALID_ANALYSIS
    assert len(llm.calls) == 3


def test_analyze_repairs_schema_violations(tmp_path) -> None:
    broken = {k: v for k, v in VALID_ANALYSIS.items() if k != "risks"}
    result, llm = _run_analyze_repair(tmp_path, [json.dumps(broken), json.dumps(VALID_ANALYSIS)])

    assert result.analysis == VALID_ANALYSIS  # repair round fixed it
    assert len(llm.calls) == 2
    repair_turn = llm.calls[1]
    # context preserved, bad output echoed as assistant turn, then fix request
    roles = [m["role"] for m in repair_turn]
    assert roles == ["system", "user", "assistant", "user"]
    assert repair_turn[2]["content"] == json.dumps(broken)
    assert "missing required field" in repair_turn[3]["content"]


def test_analyze_gates_schema_violations_when_repair_fails(tmp_path) -> None:
    # contract-complete but missing a required section -> repair round
    # gets the same prompt, still fails -> report is refused
    broken = {k: v for k, v in VALID_ANALYSIS.items() if k != "risks"}
    with pytest.raises(ReportValidationError, match="risks"):
        _run_analyze_repair(tmp_path, [json.dumps(broken), json.dumps(broken)])


def test_analyze_rejects_non_object_json(tmp_path) -> None:
    with pytest.raises(LLMError, match="not an object"):
        _run_analyze(tmp_path, json.dumps([1, 2, 3]))


def test_analyze_propagates_llm_errors(tmp_path) -> None:
    with pytest.raises(LLMError):
        _run_analyze(tmp_path, LLMError("provider down"))


def test_parse_json_response_unit() -> None:
    assert _parse_json_response('{"a": 1}') == {"a": 1}
    assert _parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_response('note: {"a": 1}') == {"a": 1}
    with pytest.raises(LLMError):
        _parse_json_response("no json here")
