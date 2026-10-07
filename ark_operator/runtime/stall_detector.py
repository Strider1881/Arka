"""Detect stalled runs (repeated action/observation or no progress)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class StallDetector:
    """Emit stall when same action+obs hash repeats 3x, or no change in N steps."""

    repeat_limit: int = 3
    no_change_limit: int = 8
    _recent: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=8))
    _unchanged_streak: int = 0
    _last_state_hash: str | None = None

    def observe(self, action_hash: str, observation_hash: str, *, state_hash: str = "") -> bool:
        """Return True if a stall is detected."""
        pair = (action_hash, observation_hash)
        self._recent.append(pair)
        if len(self._recent) >= self.repeat_limit:
            last = list(self._recent)[-self.repeat_limit :]
            if len(set(last)) == 1:
                return True
        if state_hash:
            if state_hash == self._last_state_hash:
                self._unchanged_streak += 1
            else:
                self._unchanged_streak = 0
                self._last_state_hash = state_hash
            if self._unchanged_streak >= self.no_change_limit:
                return True
        return False

    def reset(self) -> None:
        self._recent.clear()
        self._unchanged_streak = 0
        self._last_state_hash = None
