# Prompt section 3/4 — Risk and complexity analysis

## Inputs to use

- The **facts digest**: dependency list, git activity (commit cadence,
  contributor concentration), file statistics (largest files, line counts),
  tree layout, open issues/PR counts.
- The **code samples** (largest files, core modules).

## Task

1. **dependencies.notable** — which dependencies matter most to this
   project's architecture (not every dependency), and what role they play.
2. **dependencies.concerns** — dependency risks visible in the facts:
   outdated pins, heavy or abandoned libraries, unusual manifest patterns,
   platform coupling. Only what the evidence supports.
3. **risks** — concrete risks with severity (`low | medium | high`):
   code complexity hotspots (largest files / line counts), maintenance
   risk (aging repo, contributor concentration, high open-issue debt),
   architectural risks visible in the samples, test coverage indicators
   (e.g. tests/ vs src/ size), vendored or generated code problems.
   Each risk needs a mitigation.
4. **unknowns** — list every question the analysis could NOT answer from
   the facts and samples (e.g. build steps not visible, CI behavior,
   internal APIs). This section is a feature: it bounds the report's
   certainty.

## Evidence rules (apply to every claim you make)

- Every claim MUST carry `evidence`: an array of file paths from the facts.
- Severity and risk statements must be traceable to evidence; speculative
  concerns belong in `unknowns`, not in `risks`.
- Numbers (file sizes, counts, dates) come from the digest verbatim.

## Output contract

```jsonc
{
  "dependencies": {
    "notable": [ { "name": "...", "purpose": "...", "evidence": ["path"] } ],
    "concerns": [ { "description": "...", "evidence": ["path"] } ]
  },
  "risks": [ { "category": "...", "description": "...",
               "severity": "low|medium|high",
               "evidence": ["path"], "mitigation": "..." } ],
  "unknowns": [ "..." ]
}
```
