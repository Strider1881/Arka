"""LLMClient protocol with retries, timeout, and token/cost logging."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class LLMResponse(BaseModel):
    prompt_id: str
    content: Any
    raw_text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class LLMClient(Protocol):
    """All LLM calls go through this interface (SPEC §10)."""

    def complete(
        self,
        prompt_id: str,
        variables: dict[str, Any],
        *,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse: ...


class PromptNotFoundError(KeyError):
    pass
