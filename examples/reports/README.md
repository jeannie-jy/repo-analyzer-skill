# Sample Reports

Real end-to-end outputs of the pipeline, kept as reference artifacts.

## pallets/flask

Analyzed with `repo-analyzer analyze https://github.com/pallets/flask` on
2026-08-21 using `deepseek-v4-flash` (OpenAI-compatible endpoint), a
40,000-token code sample, and the default prompt assets.

| File | What it is |
|---|---|
| `report.md` | The human-readable report (what you would read first) |
| `report.json` | Structured report: analysis + evidence summary, schema-validated |
| `analysis.json` | The raw LLM reasoning, validated against the report schema |
| `sample_manifest.json` | The exact code sample fed to the LLM (paths, reasons, token estimates) — the audit trail for what the report could and could not see |

All 23 evidence citations in the report were verified against the
repository tree (100% grounding).

Reproduce with:

```
repo-analyzer analyze https://github.com/pallets/flask --output-dir output
repo-analyzer validate-report output/repos/pallets/flask/report.json
repo-analyzer verify-evidence output/repos/pallets/flask/report.json
```
