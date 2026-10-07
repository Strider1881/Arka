"""Run state machine (SPEC §6.2).

STUB: transitions + resume in P2.
"""


class Orchestrator:
    """Drives INTAKE -> ... -> COMPLETE (or ESCALATED/FAILED)."""

    def start(self, request: str) -> str:
        """Start a new run; return run_id. STUB."""
        raise NotImplementedError("STUB: Orchestrator.start (P2)")
