# Evaluation Baseline (Phase 8)

First measurement of the six metrics from ARCHITECTURE.md section 10 on
three gold cases. The deterministic metrics (structure, entrypoints,
grounding) are computed from pinned refs and cost zero LLM calls; the
judge metrics cost one LLM call per analyzed report.

## Method

- **Cases**: `evals/cases/<repo>/{repo.json, gold.json, README.md}`.
  `repo.json` pins url + ref so every run extracts the same snapshot.
  `gold.json` holds hand-annotated entrypoints and expected paths.
- **Deterministic metrics**: run `repo-analyzer eval` (no LLM key
  needed). Facts are re-extracted for the pinned ref and cached under
  the output dir; grounding reuses the existing `report.json`.
- **Judge**: `--judge` scores existing reports with an LLM-as-judge
  (deepseek-v4-flash) on a 1-5 rubric: coverage, grounding,
  correctness, actionability, plus overall usefulness.
- **Reproduce**: `repo-analyzer eval --output-dir output --judge`
  (full results in `baseline.json`).

## Results (2026-08-22)

| Case | Type | Structure | Entrypoint P/R/F1 | Grounding | Halluc. | Judge (c/g/c/a, useful) |
|---|---|---|---|---|---|---|
| charmbracelet/gum | small Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | n/a (no report) | n/a | n/a |
| pallets/flask | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 23/23 | **0%** | 5/3/3/5, 4 |
| pallets/click | pure Python library | 10/10 (100%) | 0.00 / 0.00 / **0.00** | n/a (no report) | n/a | n/a |

## Reading the numbers

1. **Structure extraction is exact (28/28 gold paths).** The tree is
   deterministic API data — this metric is a guard against regressions,
   not a real risk, and it holds.

2. **Entrypoint F1 tracks repository shape, as designed.** The heuristics
   are deliberately greedy (high recall): flask recalls all three real
   entries (R=1.0) at the cost of three expected false positives
   (`sansio/app.py` base class, two `tests/test_apps` apps). The LLM
   phase re-ranks and drops those — the eval case note says so. Gum is
   the best-case shape (single-entry CLI) at F1=1.0. Click exposes a
   real blind spot: **library-only repos have no detectable entry** by
   deterministic rules (no console scripts, no `__main__`, no server),
   so recall is 0 and only the LLM can name the import surface. This is
   recorded in the case README rather than hidden.

3. **Grounding is clean: 0% hallucination** on the flask report
   (23/23 citations verified against the tree), which is the pipeline's
   hardest guarantee.

4. **Judge scores the report useful (4/5) with strengths and
   weaknesses**: coverage 5 and actionability 5 (the report is
   comprehensive and contribution suggestions are concrete), but
   grounding 3 / correctness 3 — the judge flagged that some claims'
   evidence paths are indirect (cited files that imply, not prove, the
   claim). That is the next lever: tighten the prompt's evidence rules
   toward "path must directly support the claim", then re-judge.

## Known limitations

- Judge scores are single-run, single-model (deepseek-v4-flash); no
  ensemble or cross-model check yet.
- Click/gum cases have no report yet; judge and grounding columns are
  n/a until `analyze` runs exist for them.
- Gold annotations are the author's manual review, not crowd-verified.
