"""Tool registry for dependency injection into the executor.

STUB: P2.
"""


class ToolRegistry:
    """Name -> Tool lookup."""

    def get(self, name: str) -> object:
        """Return a registered tool. STUB."""
        raise NotImplementedError("STUB: ToolRegistry.get (P2)")
