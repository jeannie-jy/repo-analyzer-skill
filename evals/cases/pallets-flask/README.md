# Case: pallets/flask

The flagship case: a medium-sized Python framework (WSGI core + sansio
split + Click CLI), annotated from a real extraction and manual review.

Gold entry points: the three real ways to start Flask (`flask` console
script, `python -m flask`, and the WSGI `Flask` class entry). The
greedy deterministic heuristics also flag `sansio/app.py` and the
`tests/test_apps/*` apps — expected false positives that the LLM phase
should re-rank away.
