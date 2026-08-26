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

## Results (2026-08-23) — evidence directness re-measure

Roadmap item 1 ("tighten evidence rules") landed: "the cited file's
content must itself show the claim" is now a prompt-level rule in the
CLI output contract and all four `skill/prompts/*.md` sections, and the
judge rubric's grounding definition gained the same directness wording.
The flask report was regenerated with the new prompts (same pinned
ref, `d318b6834`); the pre-rule report was re-judged under the new
rubric for an A/B. Judge scores are N-run medians (6 runs new, 4 runs
old — single-run variance is real, see limitations).

| Case | Type | Structure | Entrypoint P/R/F1 | Grounding | Halluc. | Judge (c/g/c/a, useful) |
|---|---|---|---|---|---|---|
| pallets/flask, new rules | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 18/18 | **0%** | 5/3.5/4/4, 4 |
| pallets/flask, old rules (A/B) | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 23/23 | **0%** | 5/3/4.5/5, 4 |

The rule changed the report's content as designed: citations tightened
from 23 to 18 (all still verified, 0% hallucination), and direct-path
selection is visible in the output — e.g. the tech-stack row for the
`flask` console command now cites `pyproject.toml` (the `[project].scripts`
entry) and `src/flask/cli.py` (the `FlaskGroup` definition) where the
pre-rule report cited related-but-unproving files. The old report's
"1,855 commits in a 30-day window of 16 commits" contradiction is gone
from the new report.

The judge medians barely moved (grounding 3.5 vs 3, everything else
overlapping): the effect is real but smaller than judge variance at
N=4-6 (the old report scored grounding 5 in one run and 3 in three
others; the new report scored grounding 2 in one run). Both reports
share the one recurring deduction — see limitations.

## Results (2026-08-24) — library blind spot closed

Roadmap item 2 landed: a deterministic library-package-root heuristic in
`extract/entrypoints.py` (step 6) emits the package root `__init__.py`
as a `library_api` candidate when no `cli`/`http_server` candidate
exists — for a pure library, the import surface IS the entry. Click's
entrypoint F1 went from 0.00 to 1.00; gum and flask are unchanged
(regression guard: the skip rule fires for flask's console scripts, and
gum is Go with no `__init__.py`). Click and gum now have full reports,
so their grounding and judge columns are filled. Judge scores are N=3
medians; grounding is the mechanical `verify-evidence` count.

| Case | Type | Structure | Entrypoint P/R/F1 | Grounding | Halluc. | Judge (c/g/c/a, useful) |
|---|---|---|---|---|---|---|
| charmbracelet/gum | small Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | 20/20 | **0%** | 5/3/4/5, 4 |
| pallets/click | pure Python library | 10/10 (100%) | 1.00 / 1.00 / **1.00** | 19/19 | **0%** | 5/4/4/5, 5 |

(flask rows unchanged from 2026-08-23: 0.67 entrypoint F1 with the same
three expected false positives, 18/18 grounding, judge 5/4/4/4, 4.)

The click report's entry_points section names `src/click/__init__.py`
as kind `library_api` with invocation `import click`; the LLM raised
the deterministic 0.40 confidence to 0.90 after sampling showed a
coherent public API (re-exports of Command/Group/Context/Parameter) —
the prompt contract working as designed. Judge comments on both new
reports recur on the documented digest-metric deduction (gum's GitHub
statistics and contributor commit counts cited to `README.md`, which
cannot contain them; click's version-specific claims that only a
changelog proves) — consistent with flask's recurring deduction.

Method note: this run's `baseline.json` was rebuilt from the fresh
pinned-ref facts and reports on disk plus direct `judge_report` calls
(the exact function `eval --judge` uses) — because `eval` re-extracts
every case on every invocation, six full eval runs would exceed the
tokenless GitHub budget (60 req/hr per IP). A `GITHUB_TOKEN` was
configured on 2026-08-24, so `repo-analyzer eval --output-dir output
--judge` now reproduces these numbers end to end.

## Results (2026-08-27) — digest-metric deduction closed

Roadmap item (digest metrics) landed: reports now carry a deterministic
`digest_facts` annex — pipeline-computed from `RepoFacts`, never
LLM-authored — rendered as a "Verified Facts" section before Overview.
The judge rubric grants an exemption: a claim whose number matches the
section is fully grounded; a value that differs from it, or a number
the section does not list, counts against grounding. The prompt
contract's vacuous "the path the digest attributes it to" exemption now
points at the section, and digest facts are never `unknowns`. Zero
schema change; reports without the annex (e.g. the `examples/` flask
report) render and judge exactly as before.

All three reports were regenerated (refs are live `main` — the
snapshots moved since 08-24, so numbers differ from earlier rows; the
annex is self-consistent ground truth for the new snapshot). Judge
scores are N=3 medians; grounding is the mechanical `verify-evidence`
count.

| Case | Type | Structure | Entrypoint P/R/F1 | Grounding | Halluc. | Judge (c/g/c/a, useful) |
|---|---|---|---|---|---|---|
| charmbracelet/gum | small Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | 18/18 | **0%** | 5/5/5/5, 5 |
| pallets/click | pure Python library | 10/10 (100%) | 1.00 / 1.00 / **1.00** | 15/15 | **0%** | 5/4/5/5, 5 |
| pallets/flask | medium Python framework | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 16/16 | **0%** | 5/5/5/5, 5 |

Grounding medians: gum 3 → 5, flask 3.5 → 5 (vs the 08-23/08-24 rows),
click stays 4. Correctness and usefulness also moved up (gum 4→5,
flask 4→5). The primary signal is the judge's comments, not the
medians (single-run variance is ±2):

- The recurring deduction language is gone: no more "PR/issue counts
  cited to README.md, which cannot contain them", no more "file
  size/line counts citing the file itself", no more "commit counts
  cited to CHANGES.rst". Instead the judge names the section
  approvingly: "the 'Verified Facts' section is clearly labeled as
  pipeline-computed ground truth" (gum), "numbers match the Verified
  Facts section" (click), "pipeline-computed facts are restated
  accurately" (flask).
- Remaining deductions are out of annex scope and legitimate:
  inferences (gum's testing strategy), uncited assertions ("one of the
  largest and most active repos in the Pallets ecosystem"), and a
  correctness flag on a claimed module path (`charm.land/gum/v2`).

A/B under the SAME new rubric: the pre-annex flask report
(`examples/reports/pallets-flask`, no annex section) judges grounding
2/4/3 → median 3 — the same structural deductions recur, including the
"1,855 commits in a 30-day window of 16 commits" fusion error, which
the judge now catches against the annex's ground truth in the new
report. The exemption is the annex, not a looser rubric.

## Reading the numbers

1. **Structure extraction is exact (28/28 gold paths).** The tree is
   deterministic API data — this metric is a guard against regressions,
   not a real risk, and it holds.

2. **Entrypoint F1 tracks repository shape, as designed.** The heuristics
   are deliberately greedy (high recall): flask recalls all three real
   entries (R=1.0) at the cost of three expected false positives
   (`sansio/app.py` base class, two `tests/test_apps` apps). The LLM
   phase re-ranks and drops those — the eval case note says so. Gum is
   the best-case shape (single-entry CLI) at F1=1.0. Click's library
   blind spot (F1 was 0.00 — no console scripts, no `__main__`, no
   server) is closed by the library-package-root heuristic: when no
   `cli`/`http_server` candidate exists, the strongest package root
   (`<pkg>/__init__.py` or `src/<pkg>/__init__.py`, ≥2 .py files,
   tests/docs/examples excluded, src-layout beats top-level) becomes a
   `library_api` candidate at conf 0.40, and the LLM confirms it from
   the sampled `__init__.py`. The guard is deliberately narrow
   (cli/http_server only) so build/CI artifacts never suppress a real
   import surface; the ≥2-file and excluded-dir rules bound false
   positives. Click now measures F1=1.0.

3. **Grounding is clean: 0% hallucination** on both flask reports
   (23/23 and 18/18 citations verified against the tree), which is the
   pipeline's hardest guarantee — and it survived the citation
   tightening.

4. **The directness rule is measured, not assumed.** New vs old report
   under the same (tightened) rubric: grounding median 3.5 vs 3. The
   rule changed content (18 vs 23 citations, direct paths, the
   contradiction removed) but did not move the judge beyond noise at
   N=4-6 — variance dominates. What the judge *does* flag,
   consistently, on both reports: claims restating digest-verified
   metrics that no file's content can prove — commit counts (citing
   `CHANGES.rst`) and file size/line counts (citing the file itself,
   whose content does not state its own size). These are digest-facts
   with no file path that demonstrates them; the schema requires at
   least one evidence path, so the report cites the subject path and
   the judge deducts. Closed 2026-08-27: the report now carries a
   deterministic `digest_facts` annex ("Verified Facts" section) that
   gives the judge the ground truth, and the rubric exempts claims
   matching it — grounding medians 3.5→5 (flask), 3→5 (gum); see the
   08-27 section and its A/B.

## Known limitations

- Judge scores are single-model (deepseek-v4-flash) with high run
  variance: the same report scored grounding 3 and 5 across runs.
  Medians over N=4-6 are reported, but the spread is wider than the
  prompt effects measured so far.
- All three cases now have reports; grounding is verified for all of
  them (flask 16/16, click 15/15, gum 18/18 on the 08-27 snapshot —
  0% hallucination each).
- `eval` re-extracts every case on every invocation, so a full
  `--judge` run costs roughly 15 GitHub API requests per case and a
  tokenless budget (60 req/hr per IP) cannot hold repeated judge runs —
  the 2026-08-24 numbers were assembled from fresh pinned-ref facts
  plus direct `judge_report` calls, and two parallel `analyze` runs
  burst the tokenless budget mid-sampling (extraction succeeded, the
  sample stage 403'd). A `GITHUB_TOKEN` in `.env` removes the
  constraint; re-verification is one `repo-analyzer eval --judge` away.
- Gold annotations are the author's manual review, not crowd-verified.
- The analyzer hardens against provider flakiness (parse retries,
  `LLM_MAX_OUTPUT_TOKENS=32768`), but large reports still occasionally
  need a retry, and the judge call itself can return outlier scores.
