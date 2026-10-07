"""Base tool protocol: name, JSON schema, risk, timeout, typed results.

STUB: full protocol in P2/P3.
"""

from typing import Protocol


class Tool(Protocol):
    """Every tool declares metadata and returns a typed result or Failure."""

    name: str

    def run(self, args: dict[str, object]) -> object:
        """Execute the tool. STUB implementations raise NotImplementedError."""
        ...
