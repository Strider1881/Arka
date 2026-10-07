"""Per-run budgets: max steps, wall time, tokens/cost (SPEC §6.5)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BudgetConfig:
    max_steps: int = 200
    max_wall_seconds: float = 600.0
    max_tokens: int = 200_000
    max_cost_usd: float = 5.0
    warn_ratio: float = 0.8


@dataclass
class Budgets:
    """Track and enforce run budgets; emit warning at 80%."""

    config: BudgetConfig = field(default_factory=BudgetConfig)
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    started_at: float = field(default_factory=time.monotonic)
    warned: bool = False

    def record_step(self) -> None:
        self.steps += 1

    def record_llm(self, tokens: int, cost_usd: float = 0.0) -> None:
        self.tokens += tokens
        self.cost_usd += cost_usd

    def wall_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def ratios(self) -> dict[str, float]:
        return {
            "steps": self.steps / max(self.config.max_steps, 1),
            "wall": self.wall_seconds() / max(self.config.max_wall_seconds, 1.0),
            "tokens": self.tokens / max(self.config.max_tokens, 1),
            "cost": self.cost_usd / max(self.config.max_cost_usd, 1e-9),
        }

    def should_warn(self) -> bool:
        if self.warned:
            return False
        return any(r >= self.config.warn_ratio for r in self.ratios().values())

    def mark_warned(self) -> None:
        self.warned = True

    def exhausted(self) -> bool:
        return any(r >= 1.0 for r in self.ratios().values())

    def check(self) -> str | None:
        """Return 'warning', 'exhausted', or None."""
        if self.exhausted():
            return "exhausted"
        if self.should_warn():
            return "warning"
        return None
