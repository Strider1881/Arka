"""Recovery taxonomy coverage."""

from __future__ import annotations

from ark_operator.domain.enums import FailureKind
from ark_operator.domain.models import Failure
from ark_operator.runtime.recovery import Recovery
from ark_operator.tools.base import ToolResult


def test_classify_and_policy_block() -> None:
    rec = Recovery(max_transient_retries=2)
    assert rec.classify(None, http_status=503) == FailureKind.TRANSIENT
    assert rec.classify(None) == FailureKind.UNRECOVERABLE
    f = Failure(kind=FailureKind.POLICY_BLOCK, message="denied")
    assert rec.handle("k", f) is f


def test_transient_retry_succeeds() -> None:
    rec = Recovery(max_transient_retries=3)
    calls = {"n": 0}

    def retry() -> ToolResult:
        calls["n"] += 1
        if calls["n"] < 2:
            return ToolResult(
                ok=False,
                failure=Failure(kind=FailureKind.TRANSIENT, message="flaky", retryable=True),
            )
        return ToolResult(ok=True, data={"ok": True})

    out = rec.handle(
        "submit",
        Failure(kind=FailureKind.TRANSIENT, message="flaky", retryable=True),
        retry=retry,
    )
    assert isinstance(out, ToolResult)
    assert out.ok is True
    rec.reset()
    rec.reset("submit")


def test_auth_expired_relogin() -> None:
    rec = Recovery()

    def relogin() -> ToolResult:
        return ToolResult(ok=True)

    def retry() -> ToolResult:
        return ToolResult(ok=True, data={"resumed": True})

    out = rec.handle(
        "k",
        Failure(kind=FailureKind.AUTH_EXPIRED, message="login", retryable=True),
        retry=retry,
        relogin=relogin,
    )
    assert isinstance(out, ToolResult) and out.ok
