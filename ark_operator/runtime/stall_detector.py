"""Detect stalled runs (repeated action/observation or no progress).

STUB: P2.
"""


class StallDetector:
    """Emit STALL_DETECTED and trigger replan/escalate when stuck."""

    def observe(self, action_hash: str, observation_hash: str) -> bool:
        """Return True if a stall is detected. STUB."""
        raise NotImplementedError("STUB: StallDetector.observe (P2)")
