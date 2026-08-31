"""CLI integration tests: real main() against a local mock GitHub + LLM.

``ThreadingHTTPServer`` stands in for api.github.com and the LLM endpoint;
raw.githubusercontent fetches (best-effort line counts) are stubbed. This
covers command orchestration, exit codes, and artifact writes — the
network plumbing itself is covered by test_github_client.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from repo_analyzer.cli import main
from repo_analyzer.config import Settings
from repo_analyzer.models import (
    ANALYSIS_FILENAME,
    FACTS_FILENAME,
    REPORT_FILENAME,
    REPORT_MD_FILENAME,
    SAMPLE_MANIFEST_FILENAME,
)

from .test_analyze_pipeline import VALID_ANALYSIS
from .test_facts_pipeline import FIXTURES, REF

NOT_FOUND = (404, {}, b'{"message": "Not Found"}')


def _contents(text: str) -> dict:
    """A contents-API payload carrying ``text`` as base64."""
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "size": len(text),
    }


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, dict, bytes]] = {}
    posts: list[dict] = []

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        key = path
        if path in self.routes:
            pass
        elif path + "?since" in self.routes and "since" in query:
            key = path + "?since"
        elif path + "?sha" in self.routes and "sha" in query:
            key = path + "?sha"
        self._respond(self.routes.get(key, NOT_FOUND))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.posts.append(body)
        # per-model judge responses: /v1/models/<model> routes let the
        # ensemble test feed each judge model its own score
        if (self.path == "/v1/chat/completions"
                and isinstance(body, dict) and body.get("model")):
            model_route = f"/v1/models/{body['model']}"
            if model_route in self.routes:
                self._respond(self.routes[model_route])
                return
        self._respond(self.routes.get(self.path, NOT_FOUND))

    def _respond(self, entry: tuple[int, dict, bytes]) -> None:
        status, headers, body = entry
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():
    _Handler.routes = _github_routes()
    _Handler.posts = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _github_routes() -> dict[str, tuple[int, dict, bytes]]:
    """The same fixtures test_facts_pipeline routes, as HTTP responses."""
    routes: dict[str, tuple[int, dict, bytes]] = {}
    json_headers = {"Content-Type": "application/json"}

    def j(path: str, data) -> None:
        routes["/" + path] = (200, json_headers, json.dumps(data).encode("utf-8"))

    j("repos/pallets/flask", json.loads((FIXTURES / "repo_api.json").read_text(encoding="utf-8")))
    j("repos/pallets/flask/git/trees/main", json.loads((FIXTURES / "tree_flask.json").read_text(encoding="utf-8")))
    j("repos/pallets/flask/languages", {"Python": 100_000, "HTML": 20_000})
    j("repos/pallets/flask/commits?sha", [{"sha": "abc123", "commit": {"committer": {"date": "2026-08-01T12:00:00Z"}}}])
    j("repos/pallets/flask/commits?since", [{"sha": "x"}] * 3)
    j("repos/pallets/flask/contributors", [{"login": "alice", "contributions": 10}])
    routes["/repos/pallets/flask/pulls"] = (200, {"Link": "", **json_headers}, b"[]")

    pyproject = (FIXTURES / "manifest_pyproject.toml").read_text(encoding="utf-8")
    requirements = (FIXTURES / "manifest_requirements.txt").read_text(encoding="utf-8")
    dockerfile = (FIXTURES / "manifest_dockerfile").read_text(encoding="utf-8")
    package_json = '{"scripts": {"start": "node bin/www"}, "dependencies": {"express": "^5.0.0"}}'
    for path, text in [
        ("pyproject.toml", pyproject),
        ("requirements.txt", requirements),
        ("Dockerfile", dockerfile),
        ("package.json", package_json),
    ]:
        j(f"repos/pallets/flask/contents/{path}", _contents(text))
    j("repos/pallets/flask/readme", _contents((FIXTURES / "README_sample.md").read_text(encoding="utf-8")))

    routes["/v1/chat/completions"] = (
        200,
        json_headers,
        json.dumps({"choices": [{"message": {"content": json.dumps(VALID_ANALYSIS)}}]}).encode("utf-8"),
    )
    return routes


def _noop_raw(_ref, _branch, _path) -> str:
    return "line1\nline2\n"


def _patch_settings(
    monkeypatch, server_url: str, tmp_path: Path, *, api_key: str = "sk-test",
    report_language: str = "en", judge_api_key: str | None = None,
    judge_base_url: str | None = None, judge_model: str | None = None,
) -> Settings:
    settings = Settings(
        github_api_url=server_url,
        llm_base_url=f"{server_url}/v1",
        llm_api_key=api_key,
        llm_model="fake-model",
        output_dir=str(tmp_path),
        token_budget=40_000,
        report_language=report_language,
        judge_api_key=judge_api_key,
        judge_base_url=judge_base_url,
        judge_model=judge_model,
    )
    monkeypatch.setattr(Settings, "from_env", lambda: settings)
    monkeypatch.setattr("repo_analyzer.extract.file_stats._fetch_raw", _noop_raw)
    return settings


def test_extract_writes_facts(tmp_path, server, monkeypatch, capsys) -> None:
    _patch_settings(monkeypatch, server, tmp_path)
    code = main(["extract", str(REF.url)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Extracted facts" in out
    assert "pallets/flask" in out

    written = tmp_path / "repos" / "pallets" / "flask" / FACTS_FILENAME
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["metadata"]["stars"] == 71123
    assert data["repo"]["branch"] == "main"


def test_extract_404_repo_exits_1(tmp_path, server, monkeypatch) -> None:
    settings = _patch_settings(monkeypatch, server, tmp_path)
    _Handler.routes.clear()  # nothing routed -> every API call 404s
    code = main(["extract", "https://github.com/ghost/repo"])
    assert code == 1  # RepoNotFoundError -> RepoAnalyzerError exit code


def test_analyze_without_llm_key_exits_2(tmp_path, server, monkeypatch, capsys) -> None:
    _patch_settings(monkeypatch, server, tmp_path, api_key="")
    code = main(["analyze", str(REF.url)])
    assert code == 2  # ConfigError fail-fast, before any API call
    assert "LLM_API_KEY" in capsys.readouterr().err


def test_analyze_full_pipeline_writes_all_artifacts(tmp_path, server, monkeypatch, capsys) -> None:
    _patch_settings(monkeypatch, server, tmp_path)
    code = main(["analyze", str(REF.url)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Report written" in out
    assert "fake-model" in out
    assert "grounding" in out

    workdir = tmp_path / "repos" / "pallets" / "flask"
    for name in (ANALYSIS_FILENAME, SAMPLE_MANIFEST_FILENAME, REPORT_FILENAME, REPORT_MD_FILENAME):
        assert (workdir / name).exists(), name
    report = json.loads((workdir / REPORT_FILENAME).read_text(encoding="utf-8"))
    assert report["analysis"]["overview"]["summary"]
    assert report["evidence_summary"]["unverified"] == 0


def test_analyze_passes_report_language(tmp_path, server, monkeypatch, capsys) -> None:
    # REPORT_LANGUAGE=zh flows settings -> cli -> pipeline -> render:
    # report.json records it and report.md renders zh labels.
    _patch_settings(monkeypatch, server, tmp_path, report_language="zh")
    code = main(["analyze", str(REF.url)])
    assert code == 0

    workdir = tmp_path / "repos" / "pallets" / "flask"
    report = json.loads((workdir / REPORT_FILENAME).read_text(encoding="utf-8"))
    assert report["language"] == "zh"
    md = (workdir / REPORT_MD_FILENAME).read_text(encoding="utf-8")
    assert "# 仓库分析报告: pallets/flask" in md
    assert "## 概述" in md


def test_eval_judge_ensemble_two_models(tmp_path, server, monkeypatch, capsys) -> None:
    # a real report.md must exist before the judge can score it
    _patch_settings(monkeypatch, server, tmp_path,
                    judge_api_key="sk-judge", judge_model="fake-judge")
    assert main(["analyze", str(REF.url)]) == 0
    _Handler.posts = []  # isolate the eval phase's judge calls

    case_dir = tmp_path / "cases" / "flask"
    case_dir.mkdir(parents=True)
    (case_dir / "repo.json").write_text(
        json.dumps({"url": str(REF.url)}), encoding="utf-8")
    (case_dir / "gold.json").write_text(
        json.dumps({"entrypoints": [{"path": "flask/__init__.py"}]}),
        encoding="utf-8")

    # each judge model gets its own scores; JUDGE_BASE_URL is unset, so
    # the second judge falls back to the main LLM's endpoint
    def _judge(coverage: int, grounding: int) -> dict:
        return {"choices": [{"message": {"content": json.dumps({
            "coverage": coverage, "grounding": grounding, "correctness": 4,
            "actionability": 4, "usefulness": 4, "comments": "m"})}}]}

    headers = {"Content-Type": "application/json"}
    for model, coverage, grounding in [("fake-model", 4, 5), ("fake-judge", 5, 3)]:
        _Handler.routes[f"/v1/models/{model}"] = (
            200, headers, json.dumps(_judge(coverage, grounding)).encode())

    code = main(["eval", "--judge", str(case_dir), "-o", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    # flat judge line is the median across models
    assert "coverage 4.5 grounding 4" in out
    # per-model line lists both judges with their own scores
    assert "fake-model 4/5/4/4,4 | fake-judge 5/3/4/4,4" in out
    # exactly one judge call per model (the analyze phase is already done)
    assert [p["model"] for p in _Handler.posts] == ["fake-model", "fake-judge"]


def test_sample_code_command_lists_files(tmp_path, server, monkeypatch, capsys) -> None:
    _patch_settings(monkeypatch, server, tmp_path)
    code = main(["sample-code", str(REF.url)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Sampled" in out
    assert "tokens" in out


def test_validate_report_accepts_and_rejects(tmp_path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"schema_version": "1.0", "analysis": VALID_ANALYSIS}), encoding="utf-8")
    assert main(["validate-report", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "1.0", "analysis": {"overview": {}}}), encoding="utf-8")
    assert main(["validate-report", str(bad)]) == 1

    # the deterministic digest annex is a top-level sibling of analysis —
    # validate-report only checks the analysis subtree, so it passes
    with_annex = tmp_path / "with_annex.json"
    with_annex.write_text(
        json.dumps(
            {"schema_version": "1.0", "analysis": VALID_ANALYSIS,
             "digest_facts": {"git": {"commits_last_30d": 3}}}
        ),
        encoding="utf-8",
    )
    assert main(["validate-report", str(with_annex)]) == 0


def test_verify_evidence_grounding(tmp_path, capsys) -> None:
    facts = tmp_path / FACTS_FILENAME
    facts.write_text(
        json.dumps({"tree": {"entries": [{"path": "src/app.py", "type": "blob", "size": 10, "sha": "s"}]}}),
        encoding="utf-8",
    )
    report = tmp_path / REPORT_FILENAME
    report.write_text(
        json.dumps({"analysis": {"overview": {"summary": "x", "evidence": ["src/app.py"]}}}),
        encoding="utf-8",
    )
    assert main(["verify-evidence", str(report)]) == 0
    assert "1 verified" in capsys.readouterr().out


def test_verify_evidence_missing_facts_exits_2(tmp_path) -> None:
    report = tmp_path / REPORT_FILENAME
    report.write_text(json.dumps({"analysis": {"overview": {"summary": "x", "evidence": []}}}), encoding="utf-8")
    assert main(["verify-evidence", str(report)]) == 2  # InputError: repo_facts.json not found


def test_load_json_input_errors(tmp_path, capsys) -> None:
    missing = tmp_path / "nope.json"
    assert main(["validate-report", str(missing)]) == 2
    assert "File not found" in capsys.readouterr().err

    broken = tmp_path / "broken.json"
    broken.write_text("not json {", encoding="utf-8")
    assert main(["validate-report", str(broken)]) == 2
    assert "Invalid JSON" in capsys.readouterr().err

    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    assert main(["validate-report", str(not_object)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_version_flag() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_unknown_command_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate", "https://github.com/x/y"])
    assert exc.value.code == 2
