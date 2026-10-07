"""Playwright Chromium browser tool (SPEC §6.7).

STUB: observation format + actions in P3.
Also documents a DesktopTool adapter interface (STUB only) for computer-use.
"""


class BrowserTool:
    """Persistent context per run; accessibility-tree observations."""

    name = "browser"

    def run(self, args: dict[str, object]) -> object:
        """Execute a browser action. STUB."""
        raise NotImplementedError("STUB: BrowserTool.run (P3)")


class DesktopTool:
    """STUB adapter interface for computer-use in Docker/Xvfb (SPEC §6.7).

    Not implemented in this take-home; reserved for future extension.
    """

    name = "desktop"

    def run(self, args: dict[str, object]) -> object:
        """STUB: DesktopTool not implemented."""
        raise NotImplementedError("STUB: DesktopTool (out of scope)")
