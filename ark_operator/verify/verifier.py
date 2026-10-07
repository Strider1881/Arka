"""Independent verifier (separate browser context + portal_api reads).

STUB: P7. The agent never grades itself (P3).
"""


class Verifier:
    """Check portal ground truth against expected decisions."""

    def verify_run(self, run_id: str) -> object:
        """Return VerificationResult. STUB."""
        raise NotImplementedError("STUB: Verifier.verify_run (P7)")
