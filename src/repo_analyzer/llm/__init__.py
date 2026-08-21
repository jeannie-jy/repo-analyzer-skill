"""LLM provider layer: a small protocol, one client, prompt assembly.

The reasoning layer talks to ``LLMClient`` only — swapping providers
(OpenAI-compatible today, Anthropic next) never touches the pipeline.
Prompts are assembled in :mod:`repo_analyzer.llm.prompts` from the
knowledge assets under ``skill/prompts/``.
"""
