"""Server-Sent Events for live progress updates (HTMX + SSE; see DECISIONS.md).

STUB: P9.
"""

from collections.abc import AsyncIterator


async def event_stream(run_id: str) -> AsyncIterator[str]:
    """Yield SSE frames for a run. STUB."""
    yield f"data: STUB run_id={run_id}\n\n"
    return
