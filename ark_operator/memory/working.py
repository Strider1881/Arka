"""Working state derived from events (compact summary for the LLM)."""

from __future__ import annotations

from ark_operator.domain.models import WorkingState
from ark_operator.events.replay import fold_working_state
from ark_operator.events.store import EventStore


def summarize_working_state(store: EventStore, run_id: str) -> WorkingState:
    """Fold events into a compact structured summary."""
    return fold_working_state(store, run_id)
