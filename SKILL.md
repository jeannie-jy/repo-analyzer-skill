---
name: repo-analyzer
description: >
  Analyze a GitHub repository into a structured, evidence-based report:
  architecture, module relationships, entry points, execution flow, risks,
  and contribution opportunities, with every claim citing a verifiable file
  path. Use when the user gives a repository URL (or local path) and wants
  to understand the codebase quickly.
---

# repo-analyzer

Turns any repository into a structured analysis report. The deterministic
work (metadata, tree, languages, dependencies, git stats, entry-point
candidates) is done by plain Python — the LLM only reasons over the facts,
never re-derives them. Every LLM claim must carry file-path evidence, which
is mechanically verified before the report ships.

This skill is the **agent-driven** entry point. The same pipeline is exposed
as the `repo-analyzer` CLI (see `docs/ARCHITECTURE.md`) — prefer the CLI
stages for reproducibility, and use them as tools in this workflow.

## When to use

- User provides a GitHub URL (or local directory path) and asks to
  understand / summarize / onboard into a codebase.
- User asks for architecture, entry points, module relationships, risks,
  or contribution opportunities of a repo.
- User wants a report to prepare for a code review or contribution.

## Prerequisites

Configured in the environment or `.env` (see `.env.example`):

| Variable | Required | Notes |
|---|---|---|
| `LLM_API_KEY` | yes (analyze) | any OpenAI-compatible endpoint |
| `LLM_BASE_URL` | no | default `https://api.openai.com/v1` |
| `LLM_MODEL` | no | default `gpt-4o-mini`; set e.g. `deepseek-chat` |
| `GITHUB_TOKEN` | no | unauthenticated rate limit is 60 req/hr; strongly recommended |
| `TOKEN_BUDGET` | no | code-sample budget, default 40000 |
| `LLM_MAX_OUTPUT_TOKENS` | no | cap for the reasoning call; raise if responses truncate |
| `LLM_REASONING_EFFORT` | no | `low`/`high`/`max` for reasoning models |

## Output artifacts

Written to `output/repos/<owner>/<repo>/` (or `--output-dir`):

| File | Contents |
|---|---|
| `repo_facts.json` | deterministic fact base — the single contract between extraction and everything downstream |
| `sample_manifest.json` | budgeted code samples (path, token estimate, reason) |
| `analysis.json` | the LLM's schema-validated analysis (13 sections) |
| `report.json` | final report with an `evidence_summary` grounding block |
| `report.md` | rendered markdown report (13 sections, each with citations) |

## Workflow

Run the steps below in order. Steps 2 and 4 are deterministic — use the CLI
so the numbers are exact. Steps 5-6 are the only LLM steps. Stop at any
step where the CLI exits non-zero and report the error to the user; do not
paper over failures.

### 1. Resolve the input

`RepoRef.from_url` accepts `https://github.com/owner/repo` (also
`.git`-suffixed, tree/blob URLs). A local path is allowed and bypasses the
GitHub API entirely. Optional `--ref` pins a branch/tag/sha; default is the
default branch.

### 2. Extract deterministic facts

```bash
repo-analyzer extract <url> [--ref X]
```

Produces `repo_facts.json`: languages, tree (with truncation flag), manifests,
dependencies, entry-point candidates (each with the heuristic rule that
produced it), git stats, file stats, README excerpt, warnings. If metadata
fails (404 / private / network), extraction aborts with a hard error —
everything downstream depends on it. Other extract modules fail
independently: they degrade to warnings + defaults, never to silence.

### 3. Read the facts digest

Read `repo_facts.json` before reasoning. All numbers in it (language shares,
file counts, dependency versions, commit counts) are ground truth — never
recompute, re-estimate, or second-guess them.

### 4. Sample code under budget

```bash
repo-analyzer sample-code <url> --budget 40000
```

Deterministic, budget-capped sampling: entry points (50% cap), manifests
(25% cap), then largest files by line count (tests/ excluded, binary and
lockfiles filtered). Produces `sample_manifest.json` with per-file token
estimates and the sampling reason. Read the sampled files (the manifest
lists paths — fetch their raw content) to ground your reasoning.

### 5. Reason over facts + code (LLM, in sections)

Build one prompt per section using the assets in `skill/prompts/`:

1. `architecture.md` — tech stack, structure, architecture, core modules
2. `code-flow.md` — entry points, execution flow, key files
3. `risk-analysis.md` — risks, dependencies.notable
4. `contribution.md` — contribution opportunities, reading order

Each section prompt takes the same inputs: the facts digest and the code
samples. Never pass raw file contents beyond the sampled set — that is the
budget.

### 6. Assemble and validate the analysis JSON

Combine the section answers into one JSON object with exactly these 13
top-level keys: `overview`, `tech_stack`, `structure`, `architecture`,
`core_modules`, `entry_points`, `execution_flow`, `key_files`,
`dependencies`, `risks`, `reading_order`, `contribution_opportunities`,
`unknowns`. The schema is the single source of truth:
`schemas/analysis_report.schema.json`. If validation fails, feed the
violations back to the LLM and repair (the CLI's `analyze` pipeline does
this automatically with a repair loop).

```bash
repo-analyzer validate-report output/repos/<owner>/<repo>/report.json
```

### 7. Verify evidence mechanically

```bash
repo-analyzer verify-evidence output/repos/<owner>/<repo>/report.json
```

Every file path cited anywhere in the analysis is checked against the real
extracted tree. Unverified paths are listed — either fix them in the report
or move them to `unknowns`. Do not ship a report with unverified citations
when they can be corrected.

### 8. Render the report

The CLI renders `report.md` from the validated analysis. Every section must
carry its citations; `unknowns` states explicitly what could not be
determined (with the reason, e.g. rate-limited, private submodule, tree
truncated).

### 9. Self-check before presenting

- Every number in the summary matches `repo_facts.json`.
- Every claim has ≥1 evidence path that directly supports it.
- Unknowns are explicit; nothing was fabricated.
- Entry points are ranked using the deterministic candidates' confidence,
  not guessed from file names alone.

## Iron rules

1. **Never guess what the script can determine.** Language shares,
   dependency versions, file counts, commit stats — quote the fact base.
   The LLM reasons about *relationships and meaning*, not *numbers*.
2. **Every claim carries file-path evidence.** A claim without a citation
   is a hallucination risk; put it in `unknowns` instead.
3. **Unknown beats fabricated.** If the tree was truncated, a file is
   private, or an API call failed — say so explicitly.
4. **Evidence must be direct.** The cited path should support the claim
   itself, not merely imply it (the eval judge flags indirect evidence).
5. **Do not invent files.** If a path you want to cite is not in the tree,
   you do not have evidence — use a path that exists.

## Degradation semantics

| Failure | Behavior |
|---|---|
| repo metadata (404 / private / network) | hard error, workflow stops |
| tree too large | truncated flag set, continue with the truncated tree |
| a manifest unreadable | warning, continue |
| rate limited | `RateLimitError` with retry-after; tell the user, don't retry blindly |
| LLM returns empty / truncated output | raise `LLM_MAX_OUTPUT_TOKENS`, set `LLM_REASONING_EFFORT=low`, or repair-validate again |
| schema violation | repair loop: send violations back, re-validate, then assert |

## Evaluation

`repo-analyzer eval` scores reports against hand-annotated gold cases
(see `evals/`): structure accuracy, entry-point precision/recall/F1,
grounding / hallucination rate, plus an LLM-as-judge rubric. Baseline:
`evals/results/baseline.md`. Run it before and after changing prompts to
measure impact.
