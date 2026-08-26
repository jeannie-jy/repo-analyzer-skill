"""Prompt assembly: digest fidelity, structure, prompt-dir fallback."""

from __future__ import annotations

from repo_analyzer.llm.prompts import (
    build_analysis_messages,
    load_prompt_sections,
    render_facts_digest,
    render_sample,
)
from repo_analyzer.pipeline.facts import extract_facts

from .test_facts_pipeline import REF, _full_client, _noop_raw


def _facts(tmp_path):
    return extract_facts(_full_client(), REF, output_dir=tmp_path, fetch_raw_fn=_noop_raw)


def test_digest_copies_verified_numbers_verbatim(tmp_path) -> None:
    digest = render_facts_digest(_facts(tmp_path))
    assert "71,123 stars" in digest
    assert "Python" in digest and "%" in digest
    assert "src/flask/app.py" in digest  # entry point candidate path
    assert "Werkzeug" in digest  # dependency with its manifest
    assert "20 entries" in digest  # tree size
    assert "PEP 621" in digest  # heuristic provenance, not a guess


def test_digest_marks_degradation(tmp_path) -> None:
    from repo_analyzer.errors import NetworkError

    from .fake_client import FakeClient

    client = (
        FakeClient()
        .route("repos/pallets/flask", {"default_branch": "main"})
        .raise_on("repos/pallets/flask/languages", NetworkError("boom"))
    )
    facts = extract_facts(client, REF, output_dir=tmp_path)
    digest = render_facts_digest(facts)
    assert "WARNINGS" in digest and "Language statistics failed" in digest


def test_messages_have_system_and_user_roles(tmp_path) -> None:
    from repo_analyzer.context.code_sampler import sample_code

    facts = _facts(tmp_path)
    sample = sample_code(_full_client(), REF, "main", facts, budget=40_000)
    messages = build_analysis_messages(facts, sample)

    assert [m["role"] for m in messages] == ["system", "user"]
    system = messages[0]["content"]
    assert "IRON RULES" in system
    assert "evidence" in system
    assert "must be DIRECT" in system
    user = messages[1]["content"]
    assert "CODE SAMPLE" in user
    assert "src/flask/app.py" in user or "pyproject.toml" in user


def test_render_sample_marks_fences_and_tokens(tmp_path) -> None:
    from repo_analyzer.context.code_sampler import sample_code

    facts = _facts(tmp_path)
    sample = sample_code(_full_client(), REF, "main", facts, budget=40_000)
    rendered = render_sample(sample)
    assert "=== CODE SAMPLE" in rendered
    assert "### pyproject.toml" in rendered  # first sampled file
    assert "```" in rendered  # fenced code blocks
    assert "```toml" in rendered
    assert "(~" in rendered and "tokens)" in rendered


def test_all_prompt_sections_share_the_directness_rule() -> None:
    """Every reasoning section carries the unified direct-evidence rule;
    a section that drifts from it fails here, not at eval time."""
    sections = load_prompt_sections()
    assert len(sections) == 4
    for section in sections:
        assert "Evidence must be DIRECT" in section
        assert "claim to `unknowns`" in section  # the replace-or-unknowns escape hatch


def test_contract_exemption_points_at_verified_facts(tmp_path) -> None:
    """Digest-number claims are anchored to the report's Verified Facts
    section (the vacuous "path the digest attributes it to" is gone)."""
    from repo_analyzer.context.code_sampler import sample_code

    facts = _facts(tmp_path)
    sample = sample_code(_full_client(), REF, "main", facts, budget=40_000)
    messages = build_analysis_messages(facts, sample)
    assert '"Verified Facts"' in messages[0]["content"]  # the CLI contract
    for section in load_prompt_sections():
        assert '"Verified Facts"' in section


def test_prompt_dir_override_and_fallback(tmp_path) -> None:
    custom = tmp_path / "prompts"
    custom.mkdir()
    (custom / "architecture.md").write_text("CUSTOM SECTION", encoding="utf-8")
    sections = load_prompt_sections(custom)
    assert sections == ["CUSTOM SECTION"]

    # a directory without prompt files -> embedded fallback, still usable
    empty = tmp_path / "empty"
    empty.mkdir()
    fallback = load_prompt_sections(empty)
    assert len(fallback) == 1
    assert "Output only JSON" in fallback[0]
    assert "directly support" in fallback[0]
