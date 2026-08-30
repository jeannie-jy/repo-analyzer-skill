# Case: sharkdp/fd

A Rust CLI crate (`[[bin]] name = "fd" path = "src/main.rs"` in
Cargo.toml; package name is `fd-find`). This case exists to make the
Cargo blind spot measurable.

Gold annotation: the only real entry point is the Cargo `[[bin]]`
target, `src/main.rs` (kind cli). The Makefile is a build/CI helper —
`make build-entry`-style heuristics may emit it as a `build_entry`
candidate (conf 0.6), which is a false positive against this gold.

Expected result on the current extractor: entrypoint F1 = 0.00 (or
recall 0/1), because no deterministic rule reads Cargo.toml `[[bin]]`
sections yet. After a Cargo bin heuristic lands, F1 should read 1.00 —
this case is the regression guard for that fix, the same role click
played for the library-package-root heuristic.
