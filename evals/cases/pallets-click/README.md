# Case: pallets/click

A pure library (no console scripts, no `__main__`, no server). Picked to
exercise the entrypoint heuristics where they are weakest: the import
surface is the only entry, and no deterministic rule detects it. The
baseline records this blind spot explicitly instead of hiding it.
