"""Deterministic FakeLLM for tests: scripted responses keyed by prompt id.

STUB: full scripting API in P2.
"""


class FakeLLM:
    """Scripted LLMClient for deterministic, free integration tests."""

    def __init__(self, scripts: dict[str, object] | None = None) -> None:
        self._scripts = scripts or {}

    def complete(self, prompt_id: str, variables: dict[str, object]) -> object:
        """Return a scripted response or raise. STUB beyond dict lookup."""
        if prompt_id not in self._scripts:
            raise KeyError(f"STUB FakeLLM: no script for prompt_id={prompt_id!r}")
        return self._scripts[prompt_id]
