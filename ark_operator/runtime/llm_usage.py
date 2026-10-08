"""Emit LLM_USAGE events for Details observability (SPEC §10)."""

from __future__ import annotations

from typing import Any

from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.base import LLMResponse
from ark_operator.runtime.budgets import Budgets


def emit_llm_usage(
    store: EventStore,
    run_id: str,
    resp: LLMResponse,
    *,
    budgets: Budgets | None = None,
    step_id: str | None = None,
) -> None:
    """Append LLM_USAGE and optionally record against run budgets."""
    if budgets is not None:
        budgets.record_llm(resp.tokens_in + resp.tokens_out, resp.cost_usd)
    store.append(
        run_id,
        EventType.LLM_USAGE,
        {
            "prompt_id": resp.prompt_id,
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "cost_usd": resp.cost_usd,
        },
        step_id=step_id,
    )


def summarize_usage(events: list[Any]) -> dict[str, Any]:
    """Aggregate tokens/cost/steps from a run's events for the Details view."""
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    tool_calls = 0
    recoveries = 0
    plan_revisions = 0
    observations = 0
    for ev in events:
        et = getattr(ev, "type", None)
        if et is None:
            et_val = ""
        elif hasattr(et, "value"):
            et_val = str(et.value)
        else:
            et_val = str(et)
        payload = getattr(ev, "payload", None) or {}
        if et_val == EventType.LLM_USAGE.value:
            tokens_in += int(payload.get("tokens_in") or 0)
            tokens_out += int(payload.get("tokens_out") or 0)
            cost_usd += float(payload.get("cost_usd") or 0.0)
        elif et_val == EventType.TOOL_CALL.value:
            tool_calls += 1
        elif et_val == EventType.RECOVERY_ATTEMPTED.value:
            recoveries += 1
        elif et_val == EventType.PLAN_REVISED.value:
            plan_revisions += 1
        elif et_val == EventType.OBSERVATION.value:
            observations += 1
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "cost_usd": round(cost_usd, 6),
        "tool_calls": tool_calls,
        "recoveries": recoveries,
        "plan_revisions": plan_revisions,
        "observations": observations,
        "event_count": len(events),
    }
