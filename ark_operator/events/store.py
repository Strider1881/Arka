"""Append-only SQLite event log (stdlib sqlite3; see docs/DECISIONS.md).

STUB: schema + fold/resume API in P2.
"""


class EventStore:
    """Persists events; run state is derived by folding (SPEC §6.1)."""

    def append(self, run_id: str, event_type: str, payload: dict[str, object]) -> None:
        """Append one event. STUB."""
        raise NotImplementedError("STUB: EventStore.append (P2)")

    def list_for_run(self, run_id: str) -> list[dict[str, object]]:
        """Return ordered events for a run. STUB."""
        raise NotImplementedError("STUB: EventStore.list_for_run (P2)")
