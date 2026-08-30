# repo-analyzer-skill

English | [中文](README.zh-CN.md)

**What:** An Agent Skill that turns any GitHub repository (or local clone) into a structured, evidence-based analysis report — architecture, module relationships, entry points, execution flow, risks, and contribution opportunities — with every claim carrying a file-path citation that is mechanically verified before the report ships.

---

## Why

Reading an unfamiliar codebase is slow and error-prone: you guess which files matter, skim the wrong ones, and end up with an understanding you cannot trust. Generic LLM summaries make it worse — they confidently invent APIs, file paths, and numbers that were never in the repo.

This project exists to make codebase understanding **fast, grounded, and auditable**:

- **Fast** — deterministic extraction and budgeted code sampling run in seconds; the LLM only reasons over a curated context, never the whole repo.
- **Grounded** — the LLM never guesses what scripts can determine (language shares, dependency versions, file counts). Every claim must cite a file path that exists.
- **Auditable** — a 13-section report plus an automated evidence check (`verify-evidence`) and a six-metric evaluation harness (`eval`). If a claim cannot be verified, it goes in `unknowns` — never in the report.


## Install

```bash
git clone https://github.com/<you>/repo-analyzer-skill
cd repo-analyzer-skill
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                              # zero runtime deps; pytest for dev
```

## Usage

### Configure

```bash
export GITHUB_TOKEN=...      # optional but recommended (60 -> 5000 req/hr)
export LLM_BASE_URL=...      # any OpenAI-compatible endpoint
export LLM_API_KEY=...       # needed for analyze / eval --judge
export LLM_MODEL=...
```

Or write the same keys to `.env` (gitignored). Full list in [.env.example](.env.example).

### Commands

```bash
repo-analyzer extract <url|path>                  # deterministic facts -> repo_facts.json
repo-analyzer sample-code <url|path> --budget 40000
repo-analyzer analyze <url|path>                  # full pipeline -> report.md + report.json
repo-analyzer validate-report output/repos/.../report.json
repo-analyzer verify-evidence output/repos/.../report.json
repo-analyzer eval --judge                        # score reports against gold cases
```

Local paths need no token and no network: `repo-analyzer extract /path/to/repo`.

### Use as an Agent Skill

Copy (or symlink) `SKILL.md` + `skill/` + `schemas/` into your agent's skills directory:

```bash
mkdir -p ~/.claude/skills/repo-analyzer           # Claude Code
cp -r SKILL.md skill schemas docs evals ~/.claude/skills/repo-analyzer/
```

The agent then resolves the input, runs the deterministic CLI stages, reasons over facts + sampled code in four prompt sections, validates its 13-key JSON (repair loop), and verifies every citation — **no `LLM_API_KEY` needed**, since the reasoning IS the agent. Codex (`~/.codex/skills/`) and other SKILL.md-compatible agents work the same way.

## Demo

Two real outputs, one per input mode — each with the command that reproduces it.

### Demo 1: Local mode (zero GitHub API, zero tokens)

Reproduce from the repo root — the same pipeline as URL mode, only the input differs:

```bash
repo-analyzer analyze .
```

Step 1 — deterministic facts (analyze runs this internally; no LLM key; the output matches line for line, the HEAD hash moves as commits land):

    Extracted facts: output\repos\local\repo-analyzer-skill-cef3623c\repo_facts.json
      repo:        local/repo-analyzer-skill (main @ 112d59bb60)
      languages:   Python, JSON, Markdown, TOML
      files:       95 (tree truncated: False)
      manifests:   1
      entrypoints: 1 candidates
      deps:        0 direct
      warnings:    1
        - local mode: metadata is minimal (no stars/issues); language shares are extension-based approximations

Step 2 — the full 13-section report (real output, `output/repos/local/repo-analyzer-skill-cef3623c/report.md`, deepseek-v4-flash, 31/32 citations verified — the 1 unverified citation is flagged, not hidden — 9 unknowns):

> **Summary:** repo-analyzer-skill is an Agent Skill (also packaged as a CLI) that turns any GitHub repository or local clone into a structured, evidence-based analysis report covering architecture, module relationships, entry points, execution flow, risks and contribution opportunities, where every claim carries a file-path citation that is mechanically verified before the report ships.
> Evidence: `README.md` `SKILL.md` `docs/ARCHITECTURE.md` `pyproject.toml`

| Category | Technology | Role |
|---|---|---|
| language | Python | The entire runtime is Python, targeting >=3.11; language share is 52.5% of bytes (274,879 B). [`pyproject.toml`] |
| tooling | Python stdlib (urllib, tomllib, dataclasses, argparse, json) | Deliberate zero-runtime-dependency stack: urllib for GitHub API, tomllib for TOML parsing, dataclasses for the fact/report contracts, argparse for the CLI. [`pyproject.toml`] [`src/repo_analyzer/extract/dependencies.py`] [`src/repo_analyzer/cli.py`] |

### Demo 2: URL mode (full GitHub API pipeline)

Reproduce (deterministic facts need no LLM key; the full report does):

```bash
repo-analyzer extract https://github.com/pallets/flask
repo-analyzer analyze https://github.com/pallets/flask
```

Excerpt from a real `analyze` run (pallets/flask @ main `d318b68347`, deepseek-v4-flash, 23/23 citations verified; full report in `examples/reports/pallets-flask/report.md`):

> **Summary:** Flask is a lightweight WSGI web application framework for Python, built on top of Werkzeug for WSGI/routing and Jinja2 for templating. It is the core library package (version 3.2.0.dev) that developers import to build web apps.
>
> **Purpose:** Developers use Flask to construct web applications by creating a Flask app object, registering routes/view functions, using blueprints for modularity, handling requests/responses, and serving templates and static files. It serves as both a library API and a CLI tool ('flask' command) for running a development server.
> Evidence: `README.md` `pyproject.toml` `src/flask/app.py` `src/flask/cli.py`

| Category | Technology | Role |
|---|---|---|
| framework | Werkzeug | Provides WSGI utilities, routing (Map, Rule, MapAdapter), HTTP exceptions, and the dev server (werkzeug.serving.run_simple) used by Flask's core request/response cycle. [`src/flask/app.py`] [`src/flask/sansio/app.py`] [`pyproject.toml`] |
| framework | Click | CLI framework; the 'flask' console script is registered as flask.cli:main, and FlaskGroup/AppGroup subclass click.Group to build the CLI command tree. [`pyproject.toml`] [`src/flask/cli.py`] |

## Architecture

```
repo URL / local path
      │
      ▼
┌───────────── Deterministic layer (code, zero LLM) ─────────────┐
│ metadata → tree → languages → manifests → dependencies →       │
│ entrypoints(heuristics) → git stats → file stats → readme      │
│                    │                                           │
│                    ▼                                           │
│         repo_facts.json  (fact base, schema v1)                │
│                    │                                           │
│         code_sampler (token budget, sampling manifest)         │
└────────────────────┬───────────────────────────────────────────┘
                     ▼
        ┌────── LLM reasoning layer ──────┐
        │ architecture.md  code-flow.md   │
        │ risk-analysis.md contribution.md│
        │        13-key JSON, schema-checked (repair loop)        │
        └────────────────┬────────────────┘
                         ▼
        report.json + report.md  (every claim cites a path)
                         ▼
        verify-evidence: citations checked against the real tree
```

**The boundary is the core design.** `repo_facts.json` is the single contract between the deterministic layer and everything downstream — prompts, reports, and evaluation all consume it, and the LLM never re-derives its numbers. Everything above the boundary is mechanical and unit-tested; everything below is reasoning over a bounded, auditable context.

## How it works

The skill drives a 9-step workflow ([SKILL.md](SKILL.md) is the agent-facing spec; the same pipeline is exposed as the `repo-analyzer` CLI):

1. **Resolve** — GitHub URL (`.git` suffix, tree/blob URLs accepted) or a local directory.
2. **Extract facts** — metadata, tree (with truncation flag), languages, manifests, dependencies, entry-point candidates (each with the heuristic rule that produced it), git stats, file stats, README excerpt. `repo-analyzer extract <url|path>`.
3. **Read the facts digest** — the fact base is ground truth; its numbers are never recomputed.
4. **Sample code under budget** — entry points (50% cap) → manifests (25% cap) → largest files (tests excluded, binaries/lockfiles filtered), token-estimated per file. `repo-analyzer sample-code`.
5. **Reason in sections** — four prompt assets (`skill/prompts/`): architecture, code flow/entry points, risks, contributions. The LLM sees only the facts digest + sampled code.
6. **Assemble and validate** — exactly 13 top-level keys per the schema (`schemas/analysis_report.schema.json`, single source of truth). Schema violations trigger a **repair loop**: violations are sent back to the LLM, it corrects its own output, and validation runs again.
7. **Verify evidence** — every cited path is checked against the real extracted tree. `repo-analyzer verify-evidence`; unverified citations are fixed or moved to `unknowns`.
8. **Render** — `report.md` with all 13 sections; `unknowns` states explicitly what could not be determined and why.
9. **Self-check** — numbers match the fact base, every claim has direct evidence, nothing fabricated.

## Features

- **13-section report** — overview, tech stack, structure, architecture, core modules, entry points, execution flow, key files, dependencies, risks, reading order, contribution opportunities, unknowns.
- **Evidence-first** — every claim carries file-path citations; `verify-evidence` reports a grounding ratio (23/23 = 0% hallucination on the flask sample).
- **Two input modes** — GitHub API (rate-limit aware, typed errors) or local directories (git snapshot or filesystem scan, zero network).
- **Budgeted context** — the LLM never sees the whole repo; sampling is deterministic and auditable per file.
- **LLM-agnostic** — any OpenAI-compatible endpoint (`LLM_BASE_URL` + `LLM_API_KEY`); works with reasoning models (`LLM_REASONING_EFFORT`, `LLM_MAX_OUTPUT_TOKENS`).
- **Honest degradation** — metadata failure is a hard error; anything else degrades to warnings + defaults, never to silence. Rate limits surface `Retry-After` instead of blind retries.
- **Zero dependencies** — Python 3.11+ stdlib only (TOML via `tomllib`, JSON, urllib, subprocess).
- **Six CLI commands** — `extract`, `analyze`, `sample-code`, `validate-report`, `verify-evidence`, `eval`.

## Design Decisions

| Decision | Why |
|---|---|
| **Deterministic layer owns all numbers** | Language shares, dependency versions, commit counts are facts, not opinions. LLM hallucination is bounded to reasoning, where it can be caught by evidence checks. |
| **Every claim cites a path** | A claim without evidence is a hallucination risk — it goes in `unknowns` instead. Evidence must be *direct* (the path supports the claim itself). |
| **Stdlib only** | Zero supply chain, works offline, installs in seconds; TOML parsing (tomllib) and HTTP (urllib) are built in on 3.11+. |
| **Schema as single source of truth** | `schemas/analysis_report.schema.json` is exported from `schema.py` — one file drives validation, prompts, and eval; a mini JSON-schema validator subset keeps it dependency-free. |
| **Budget-capped sampling** | Entry points deserve half the budget (a repo's core file is worth more than breadth); files above a single-file cap are skipped, not truncated. |
| **Repair loop over prompt nagging** | Schema violations are an engineering problem — send them back to the LLM, re-validate, then assert. |
| **Local mode mirrors remote semantics** | Git repos are analyzed from `ls-tree` (a true HEAD snapshot, same sizes/shas as the API); non-git dirs degrade to a filesystem scan with an explicit warning. |
| **Hashed workdirs for local refs** | `G:\a\proj` and `G:\b\proj` must not overwrite each other's artifacts. |
| **Honest unknowns** | Stars, issues, and PRs are not determinable locally — they stay 0/None and are flagged, never guessed. |

## Evaluation

Six metrics against hand-annotated gold cases (`repo-analyzer eval`, see [evals/results/baseline.md](evals/results/baseline.md)):

| Case | Type | Structure | Entrypoint P/R/F1 | Grounding | Halluc. | Judge (c/g/c/a, useful) |
|---|---|---|---|---|---|---|
| charmbracelet/gum | small Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | 18/18 | **0%** | 5/5/5/5, 5 |
| pallets/flask | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 16/16 | **0%** | 5/5/5/5, 5 |
| pallets/flask, pre-rule (A/B) | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 23/23 | **0%** | 5/3/4.5/5, 4 |
| pallets/click | pure Python library | 10/10 (100%) | 1.00 / 1.00 / **1.00** | 15/15 | **0%** | 5/4/5/5, 5 |
| sharkdp/fd | small Rust CLI | 9/9 (100%) | 0.00 / 0.00 / **0.00** | 16/16 | **0%** | 5/5/5/5, 5 |
| 11ty/eleventy | medium Node SSG | 9/9 (100%) | 1.00 / 1.00 / **1.00** | 12/12 | **0%** | 5/4/4/5, 5 |

What the numbers mean: structure extraction is exact; entry-point F1 tracks repository shape — gum's single-entry CLI is the best case, eleventy's single Node CLI matches it (package.json bin, F1=1.00), click's library-only layout is detected too (the deterministic package-root heuristic, Roadmap item 2, emits `src/click/__init__.py` as a `library_api` candidate; the LLM confirms it from the sampled `__init__.py`, raising the 0.40 confidence to 0.90 with an `import click` invocation), flask's 0.67 is the documented cost of greedy recall (all three real entries found, three expected false positives re-ranked away), and fd's 0.00 is the documented Cargo blind spot — no Cargo.toml `[[bin]]` detection yet, so the Makefile candidate is a false positive and `src/main.rs` a false negative; the case ships with the limitation recorded and guards the future heuristic (the click pattern). The hardest guarantee, 0% hallucination, holds on **all five** reports (flask 16/16, click 15/15, gum 18/18 on the 2026-08-27 snapshot; fd 16/16, eleventy 12/12 on the 2026-08-30 snapshot). The 2026-08-27 rows re-measure after Roadmap item 3 (digest-metric deduction): reports now carry a deterministic **Verified Facts** annex — pipeline-computed numbers, never LLM-authored — and the judge rubric exempts claims matching it. Grounding medians went 3 → 5 (gum) and 3.5 → 5 (flask), correctness/usefulness moved with them, and the recurring "no file's content can prove this number" deductions are gone from the judge's comments; under the same rubric the pre-annex flask report still judges grounding 3 — the exemption is the annex, not a looser rubric. The 2026-08-30 run surfaced a real annex coverage gap (eleventy's sampler-tier byte counts — `src/UserConfig.js`, `src/Template.js` — weren't listed, so the judge deducted correct numbers) and closed it: the annex's largest-files cap now matches the extractor's 15, and fd/eleventy judge 5/5/5/5,5 and 5/4/4/5,5 with only scope-legal deductions left (see [baseline.md](evals/results/baseline.md)).

## Roadmap

MVP (Phases 1-8) is complete. Next levers, in order of value:

1. ~~**Tighten evidence rules**~~ — **DONE (2026-08-23)**: "the cited file's content must itself show the claim" is now a prompt-level rule (CLI contract + all four skill prompts) and part of the judge rubric; re-measured via `eval --judge` A/B (citations 23→18, 0% hallucination held, judge medians unchanged — variance dominates).
2. ~~**Library blind spot**~~ — **DONE (2026-08-24)**: the deterministic package-root heuristic (`<pkg>/__init__.py` or `src/<pkg>/__init__.py`, ≥2 .py files, excluded dirs, suppressed only by cli/http_server candidates) emits the import surface as a `library_api` candidate; click's entrypoint F1 went 0.00 → 1.00 (P=1 R=1), flask/gum unchanged (regression guard), and the click report names `src/click/__init__.py` at confidence 0.90 with invocation `import click`.
3. ~~**Digest-metric deduction**~~ — **DONE (2026-08-27)**: reports carry a deterministic `digest_facts` annex rendered as a **Verified Facts** section (pipeline-computed from `RepoFacts`, never LLM-authored); the judge rubric exempts claims matching it (a differing value or an unlisted number counts against grounding); the prompt contract's vacuous "path the digest attributes it to" exemption points at the section. Zero schema change, old reports render byte-identical. Re-measured (N=3 medians): gum 5/5/5/5, click 5/4/5/5, flask 5/5/5/5 — grounding medians 3→5 (gum) and 3.5→5 (flask); the recurring "no file's content can prove this number" deductions are gone from judge comments, and the judge now catches the old report's 1,855-in-a-30-day-window fusion error. A/B under the same rubric: the pre-annex flask report still judges grounding 3 — the exemption is the annex, not a looser rubric.
4. ~~**More gold cases**~~ — **DONE (2026-08-30)**: `sharkdp/fd` (Rust crate) + `11ty/eleventy` (Node SSG) added, five cases total. The run documented the Cargo blind spot (fd F1=0.00 — no `[[bin]]` detection; the case guards the future heuristic) and closed an annex coverage gap it exposed (largest-files cap 8 → 15, matching the sampler tier, so every byte count the LLM can restate is listed; `RepoFacts.from_dict` added). eleventy F1=1.00 (package.json bin positive control); all older cases unchanged; judge N=3: fd 5/5/5/5,5, eleventy 5/4/4/5,5 with only scope-legal "implied" deductions.
5. **Report language coverage** — `REPORT_LANGUAGE` exists; verify and polish the zh rendering path end-to-end.
6. **Evaluation depth** — multi-model judge ensemble and per-section scoring instead of whole-report.
