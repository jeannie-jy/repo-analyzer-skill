# repo-analyzer-skill

A reusable **Agent Skill** that turns any GitHub repository into a structured, evidence-based analysis report.

Given a repository URL, it:

1. **Extracts deterministic facts** — metadata, directory tree, language statistics, dependencies, entry-point candidates, git stats — with plain Python. No LLM involved.
2. **Feeds facts + budgeted code samples to an LLM** for architecture reasoning (module relationships, execution flow, risks, contribution opportunities).
3. **Emits a schema-validated report** in which every claim carries a verifiable file-path citation.

Designed as an Agent Skill: `SKILL.md` drives an agent through the workflow, while the same pipeline is exposed as a CLI (`repo-analyzer`) for reproducibility, testing, and evaluation.

## Status

| Phase | Content | Status |
|---|---|---|
| 1 | Architecture design | ✅ done ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) |
| 2 | Project skeleton | ✅ done |
| 3 | Deterministic extraction layer | ⏳ next |
| 4 | LLM reasoning pipeline | ⏳ |
| 5 | Structured output + evidence check | ⏳ |
| 6 | First real repository end-to-end | ⏳ |
| 7 | Tests | ⏳ |
| 8 | Evaluation baseline | ⏳ |

## Installation

Requires Python 3.11+. Zero runtime dependencies — stdlib only.

```bash
git clone https://github.com/<you>/repo-analyzer-skill
cd repo-analyzer-skill
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # dev extra installs pytest only
```

## Configuration

```bash
export GITHUB_TOKEN=...          # optional but recommended (60 -> 5000 req/hr)
export LLM_BASE_URL=...          # any OpenAI-compatible endpoint
export LLM_API_KEY=...
export LLM_MODEL=...
```

See [.env.example](.env.example) for the full list of options.

## Usage

```bash
repo-analyzer analyze https://github.com/pallets/flask
```

Individual pipeline stages are exposed as subcommands (each doubles as a
tool for agent-driven runs):

```bash
repo-analyzer extract https://github.com/pallets/flask
repo-analyzer sample-code https://github.com/pallets/flask --budget 40000
repo-analyzer validate-report output/repos/pallets/flask/report.json
repo-analyzer verify-evidence output/repos/pallets/flask/report.json
```

## Design

The full architecture is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) —
the deterministic/LLM boundary, the `repo_facts.json` contract, the
evidence-first reporting mechanism, and the evaluation strategy.
