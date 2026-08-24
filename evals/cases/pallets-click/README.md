# Case: pallets/click

A pure library (no console scripts, no `__main__`, no server). The
import surface is the only entry. The baseline originally recorded this
case as an expected false negative (F1 = 0.00): no deterministic rule
detected a library-only repo's entry.

Since 2026-08-24 the deterministic library-package-root heuristic
(`_library_package_root` in `extract/entrypoints.py`) emits
`src/click/__init__.py` as a `library_api` candidate when no
cli/http_server candidate exists, so the entrypoint metrics are
measurable: F1 = 1.00 on the 2026-08-24 live run. The LLM phase still
does the semantic work — it samples the `__init__.py` and confirms or
raises the candidate's low (0.40) confidence in the report.
