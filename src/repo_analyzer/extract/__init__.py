"""Deterministic extraction layer.

Each module is a standalone, independently testable extractor that maps a
GitHub API response (or local file) into one slice of the fact base.
Nothing here calls an LLM; failures are reported as ``warnings`` by the
pipeline orchestrator, never fatal.
"""
