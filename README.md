# repo-analyzer-skill

English | [中文](README.zh-CN.md)

**What:** An Agent Skill that turns any GitHub repository (or local clone) into a structured, evidence-based analysis report — architecture, module relationships, entry points, execution flow, risks, and contribution opportunities — with every claim carrying a file-path citation that is mechanically verified before the report ships.

Zero runtime dependencies. Stdlib only. 

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

### Demo 1: Local mode (zero GitHub API, zero tokens, zero setup)

Reproduce from the repo root:

```bash
repo-analyzer extract .
```

Output (matches line for line; the HEAD hash moves as commits land):

    Extracted facts: output\repos\local\repo-analyzer-skill-cef3623c\repo_facts.json
      repo:        local/repo-analyzer-skill (main @ 112d59bb60)
      languages:   Python, JSON, Markdown, TOML
      files:       95 (tree truncated: False)
      manifests:   1
      entrypoints: 1 candidates
      deps:        0 direct
      warnings:    1
        - local mode: metadata is minimal (no stars/issues); language shares are extension-based approximations

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
| charmbracelet/gum | small Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | n/a | n/a | n/a |
| pallets/flask | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 23/23 | **0%** | 5/3/3/5, 4 |
| pallets/click | pure Python library | 10/10 (100%) | 0.00 / 0.00 / **0.00** | n/a | n/a | n/a |

What the numbers mean: structure extraction is exact; entry-point F1 tracks repository shape (gum's single-entry CLI is the best case; click's library-only layout has no deterministically detectable entry — the LLM phase names the import surface, recorded in the case README); the hardest guarantee, 0% hallucination, holds on the flask report; the judge rates the report useful (4/5) with direct-evidence tightening as the next lever.

## Roadmap

MVP (Phases 1-8) is complete. Next levers, in order of value:

1. **Tighten evidence rules** — the judge scored grounding 3/5 for indirect citations; make "path must directly support the claim" a prompt-level rule and re-measure with `eval --judge`.
2. **Library blind spot** — click's entrypoint F1 is 0.0 because pure libraries have no deterministic entry; add an LLM-phase "import surface" candidate so the LLM can name it.
3. **More gold cases** — Go monorepos, Node CLIs, Rust crates; each adds a row to the baseline and guards prompt regressions.
4. **Report language coverage** — `REPORT_LANGUAGE` exists; verify and polish the zh rendering path end-to-end.
5. **Evaluation depth** — multi-model judge ensemble and per-section scoring instead of whole-report.
