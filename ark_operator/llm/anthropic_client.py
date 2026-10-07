"""Anthropic API adapter (OPERATOR_MODEL + ANTHROPIC_API_KEY).

STUB: P2/P4.
"""


class AnthropicClient:
    """Real LLMClient backed by the Anthropic API."""

    def complete(self, prompt_id: str, variables: dict[str, object]) -> object:
        """Call Anthropic with a versioned prompt. STUB."""
        raise NotImplementedError("STUB: AnthropicClient.complete (P4)")
