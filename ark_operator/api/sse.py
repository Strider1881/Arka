"""Server-Sent Events for live progress updates (HTMX + SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from ark_operator.events.store import EventStore


async def event_stream(store: EventStore, run_id: str) -> AsyncIterator[str]:
    """Yield SSE frames for a run."""
    for ev in store.list_for_run(run_id):
        yield "data: " + json.dumps({"seq": ev.seq, "type": ev.type.value}) + "\n\n"
