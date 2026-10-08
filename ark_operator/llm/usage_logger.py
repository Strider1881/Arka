"""Wrap an LLMClient to append LLM_USAGE events (Details observability)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ark_operator.events.store import EventStore
from ark_operator.llm.base import LLMClient, LLMResponse
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.llm_usage import emit_llm_usage


class UsageLoggingLLM:
    """Delegates complete() and records tokens/cost on the event store."""

    def __init__(
        self,
        inner: LLMClient,
        store: EventStore,
        run_id: str,
        budgets: Budgets | None = None,
    ) -> None:
        self._inner = inner
        self._store = store
        self._run_id = run_id
        self._budgets = budgets

    def complete(
        self,
        prompt_id: str,
        variables: dict[str, Any],
        *,
        schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        resp = self._inner.complete(prompt_id, variables, schema=schema)
        emit_llm_usage(self._store, self._run_id, resp, budgets=self._budgets)
        return resp
