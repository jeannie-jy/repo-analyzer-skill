# Case: 11ty/eleventy

A Node.js static-site generator (`@11ty/eleventy`). Single user-facing
entry point: the `eleventy` command, mapped in package.json's `bin`
field to `cmd.cjs`.

Gold annotation: one entry point, `cmd.cjs` (kind cli). `src/Core.js`
is the library core that `cmd.cjs` instantiates — it is `main` for
programmatic use but not a separate user entry, so it is not in gold
(expected F1 stays 1.00 when the LLM keeps it out of the report's
entry_points list; the deterministic candidate set is what the metric
measures, and it should contain exactly `cmd.cjs`).

This case guards the package.json bin heuristic (positive control) and
exercises the workspace structure: `packages/browser` and
`packages/build-awesome` are npm workspace packages, not entry points.
