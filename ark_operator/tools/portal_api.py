"""Read-only portal helpers for the verifier and cheap lookups (SPEC §6.8).

STUB: P3. Never used as a shortcut for writes by the executor.
"""


class PortalApiTool:
    """Read-only AcmeCorp Procure API client."""

    name = "portal_api"

    def run(self, args: dict[str, object]) -> object:
        """Perform a read-only portal lookup. STUB."""
        raise NotImplementedError("STUB: PortalApiTool.run (P3)")
