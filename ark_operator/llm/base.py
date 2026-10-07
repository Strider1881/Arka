"""LLMClient protocol with retries, timeout, and token/cost logging.

STUB: P2.
"""

from typing import Protocol


class LLMClient(Protocol):
    """All LLM calls go through this interface (SPEC §10)."""

    def complete(self, prompt_id: str, variables: dict[str, object]) -> object:
        """Run a versioned prompt and return structured output."""
        ...
