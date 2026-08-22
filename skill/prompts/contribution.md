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

- Every claim MUST carry `evidence`: an array of file paths from the
  facts (tree paths, manifest paths, sampled file paths). Quote paths
  exactly as they appear in the digest.
- Evidence must be DIRECT: the cited file's content must itself show the
  claim (a class definition, a dependency entry, a registration call). A
  path that only relates to the claim without proving it is indirect —
  replace it with the file that demonstrates the claim, or move the
  claim to `unknowns`. A claim restating a verified fact from the digest
  is directly supported by the path the digest attributes it to.
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
