# Prompt section 1/4 — Architecture reasoning

## Inputs to use

- The **facts digest** (metadata, language shares, top-level layout, manifests,
  dependencies, entry points, git stats, file stats, README excerpt) — all
  numbers in it were verified by the extraction layer. Treat them as ground
  truth; never recompute or second-guess them.
- The **code samples** (fenced blocks with a path header and token count).

## Task

Reason about the repository's purpose and architecture:

1. **overview** — what this project is, in one short summary; what a user
   (or developer) does with it. Base it on the README excerpt, metadata,
   and the sampled code.
2. **tech_stack** — the main technologies actually visible in the facts:
   language shares, dependencies (from the facts, not guessed), manifests.
   Name concrete libraries and their role in this codebase.
3. **structure** — how the repository is organized: notable top-level
   directories and files, what lives where.
4. **architecture** — the design as you can see it in the sampled code:
   layers (if any), how data flows between components (from → to → mechanism),
   and design patterns with code evidence.
5. **core_modules** — the 3-8 modules that carry the architecture (always
   include this key; do not rename it or fold it into key_files). Each
   module: its `name`, the `path` of its main file, one-sentence
   `responsibility`, the `key_symbols` (classes/functions) that define it
   with their `location`, and its `relationships` — each an object with
   `with` (the other module), `mechanism` (how they interact), and
   `evidence` — NOT a plain string.

## Evidence rules (apply to every claim you make)

- Every claim MUST carry `evidence`: an array of file paths from the facts
  (tree paths, manifest paths, or sampled file paths). Quote paths exactly
  as they appear in the digest.
- Do not invent facts. If a number (stars, file counts, dependency versions)
  is in the facts digest, cite it verbatim. If something is not in the facts
  or the samples, say so in `unknowns` — never guess.
- Do not use more than 4 evidence paths per claim.

## Output contract

Produce JSON with exactly these top-level keys (see the caller's contract
for the full shape):

```jsonc
{
  "overview": { "summary": "...", "purpose": "...", "evidence": ["path"] },
  "tech_stack": [ { "category": "language|framework|database|tooling|other",
                    "name": "...", "role": "...", "evidence": ["path"] } ],
  "structure": { "summary": "...",
                 "notable_dirs": [ { "path": "...", "purpose": "...",
                                     "evidence": ["path"] } ] },
  "architecture": { "summary": "...", "layers": ["..."],
                    "data_flow": [ { "from": "...", "to": "...",
                                     "mechanism": "...", "evidence": ["path"] } ],
                    "patterns": ["..."] },
  "core_modules": [ { "name": "...", "path": "...", "responsibility": "...",
                      "key_symbols": [ { "symbol": "...", "location": "..." } ],
                      "relationships": [ { "with": "...", "mechanism": "...",
                                           "evidence": ["path"] } ],
                      "evidence": ["path"] } ]
}
```
