"""Deterministic FakeLLM: scripted responses keyed by prompt id."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from ark_operator.llm.base import LLMResponse, PromptNotFoundError

ScriptValue = Any | Callable[[dict[str, Any]], Any]


class FakeLLM:
    """Scripted LLMClient for deterministic, free integration tests."""

    def __init__(self, scripts: dict[str, ScriptValue] | None = None) -> None:
        self._scripts: dict[str, ScriptValue] = dict(scripts or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, prompt_id: str, value: ScriptValue) -> None:
        self._scripts[prompt_id] = value

    def complete(
        self,
        prompt_id: str,
        variables: dict[str, Any],
        *,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        self.calls.append((prompt_id, variables))
        if prompt_id not in self._scripts:
            raise PromptNotFoundError(f"FakeLLM: no script for prompt_id={prompt_id!r}")
        value = self._scripts[prompt_id]
        content = value(variables) if callable(value) else value
        if schema is not None and isinstance(content, dict):
            content = schema.model_validate(content)
        elif schema is not None and isinstance(content, BaseModel):
            content = schema.model_validate(content.model_dump())
        return LLMResponse(
            prompt_id=prompt_id,
            content=content,
            raw_text=str(content),
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
        )
