# Prompt section 2/4 — Code flow and entry points

## Inputs to use

- The **facts digest**, in particular the *entry points* table: each
  candidate already carries a deterministic `confidence` and the exact
  heuristic rule that produced it (`heuristic`). The extraction layer
  detected them mechanically — your job is to rank and explain them.
- The **code samples**, especially entry-point files, manifests with
  `bin`/`scripts`/`[project].scripts`, Dockerfiles, and Makefiles.

## Task

1. **entry_points** — re-rank the deterministic candidates by importance
   for a newcomer: which ones actually start the project? For each selected
   entry point include the `path`, a `kind` from
   `cli | http_server | worker | library_api | scheduler | other`, the
   `invocation` if the facts give one, a confidence based on BOTH the
   deterministic heuristic and the sampled code, and a short `rationale`.
   You may drop candidates the code shows are noise (e.g. a generic
   `app.py` that is not an entry point) — explain why in the rationale.
   For a library-only repo (no `cli`/`http_server` candidates), the
   import surface is the entry: name the package root `__init__.py` with
   kind `library_api`. The deterministic library candidate's low
   confidence is expected — sample the `__init__.py` and raise the
   confidence when the code shows a coherent public API.
2. **execution_flow** — the sequence of steps that happen when the
   project runs (startup path, request/command handling, key components
   touched in order).
3. **key_files** — the 5-10 files a newcomer must read first, and why.
4. **reading_order** — an ordered study path: step → target file →
   why this order helps. `step` is a short imperative string describing
   what to read or do ("Read the README, then the main entry"), NOT a
   number — the schema rejects numeric steps.

## Evidence rules (apply to every claim you make)

- Every claim MUST carry `evidence`: an array of file paths from the
  facts (tree paths, manifest paths, sampled file paths). Quote paths
  exactly as they appear in the digest.
- Evidence must be DIRECT: the cited file's content must itself show the
  claim (a class definition, a dependency entry, a registration call). A
  path that only relates to the claim without proving it is indirect —
  replace it with the file that demonstrates the claim, or move the
  claim to `unknowns`. A claim restating a verified fact from the digest
  is directly supported by the path the digest attributes it to.
- When you change a candidate's confidence or drop it, ground that in
  sampled code; otherwise keep the deterministic confidence.
- Unknown or unverifiable → `unknowns`, never guess.

## Output contract

```jsonc
{
  "entry_points": [ { "path": "...", "kind": "cli|http_server|worker|library_api|scheduler|other",
                      "invocation": "..." , "confidence": 0.0,
                      "rationale": "...", "evidence": ["path"] } ],
  "execution_flow": [ { "step": "...", "description": "...", "evidence": ["path"] } ],
  "key_files": [ { "path": "...", "why": "...", "evidence": ["path"] } ],
  "reading_order": [ { "step": "...", "target": "...", "why": "..." } ]
}
```
