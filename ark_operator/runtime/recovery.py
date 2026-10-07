"""Failure taxonomy and recovery strategies (SPEC §6.6)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ark_operator.domain.enums import FailureKind
from ark_operator.domain.models import Failure
from ark_operator.tools.base import ToolResult

BackoffFn = Callable[[], None]


@dataclass
class Recovery:
    """Classify failures and apply retries / relogin / escalate."""

    max_transient_retries: int = 3
    attempts: dict[str, int] = field(default_factory=dict)

    def classify(self, failure: Failure | None, *, http_status: int | None = None) -> FailureKind:
        if failure:
            return failure.kind
        if http_status and http_status >= 500:
            return FailureKind.TRANSIENT
        return FailureKind.UNRECOVERABLE

    def backoff(self, attempt: int) -> None:
        """Custom tiny exponential backoff with jitter (no tenacity)."""
        base = min(2**attempt * 0.05, 1.0)
        time.sleep(base + random.uniform(0, 0.05))

    def handle(
        self,
        key: str,
        failure: Failure,
        *,
        retry: Callable[[], ToolResult] | None = None,
        relogin: Callable[[], ToolResult] | None = None,
    ) -> ToolResult | Failure:
        kind = failure.kind
        if kind in {FailureKind.POLICY_BLOCK, FailureKind.DATA_CONFLICT}:
            return failure
        if kind == FailureKind.AMBIGUOUS:
            return failure
        if kind == FailureKind.AUTH_EXPIRED and relogin is not None:
            login = relogin()
            if login.ok and retry is not None:
                return retry()
            return failure
        if kind in {
            FailureKind.TRANSIENT,
            FailureKind.TIMEOUT,
            FailureKind.ELEMENT_NOT_FOUND,
            FailureKind.UI_CHANGED,
        }:
            n = self.attempts.get(key, 0)
            if n >= self.max_transient_retries or retry is None:
                return failure
            self.attempts[key] = n + 1
            self.backoff(n)
            return retry()
        return failure

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self.attempts.clear()
        else:
            self.attempts.pop(key, None)
