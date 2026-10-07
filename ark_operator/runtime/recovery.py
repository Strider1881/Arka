"""Failure taxonomy and recovery strategies (SPEC §6.6).

STUB: P5.
"""


class Recovery:
    """Classify failures and apply retries / relogin / escalate."""

    def handle(self, failure: object) -> object:
        """Attempt recovery for a typed Failure. STUB."""
        raise NotImplementedError("STUB: Recovery.handle (P5)")
