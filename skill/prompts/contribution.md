# Prompt section 4/4 — Contribution opportunities

## Inputs to use

- The **facts digest** and **code samples** (module structure, risks,
  key files) — reuse your own earlier reasoning where it is grounded.

## Task

Propose concrete, actionable contribution opportunities for a newcomer:

- Each opportunity must name the exact area and the files it touches
  (`related_files`), and a realistic difficulty
  (`low | medium | high`).
- Prefer opportunities the evidence supports: missing tests around a
  core module, a complexity hotspot, a dependency concern, a TODO-visible
  gap in the samples, documentation gaps (README excerpt vs. surface
  area). Do not invent project plans.

## Evidence rules

- Every opportunity MUST carry `evidence`: an array of file paths from
  the facts.
- "Low difficulty" means a bounded change in one file; be honest about
  scope — a claim of easy work that isn't is worse than no claim.

## Output contract

```jsonc
{
  "contribution_opportunities": [ { "area": "...", "description": "...",
      "difficulty": "low|medium|high",
      "related_files": ["path"],
      "evidence": ["path"] } ]
}
```
