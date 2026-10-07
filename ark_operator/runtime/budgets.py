"""Per-run budgets: max steps, wall time, tokens/cost (SPEC §6.5).

STUB: P2.
"""


class Budgets:
    """Track and enforce run budgets; emit BUDGET_WARNING at 80%."""

    def check(self) -> None:
        """Raise or warn if budgets exceeded. STUB."""
        raise NotImplementedError("STUB: Budgets.check (P2)")
