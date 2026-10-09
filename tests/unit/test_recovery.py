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
    assert (
        rec.classify(Failure(kind=FailureKind.AUTH_EXPIRED, message="x", retryable=True))
        == FailureKind.AUTH_EXPIRED
    )
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


def test_ambiguous_and_auth_without_helpers() -> None:
    rec = Recovery(max_transient_retries=1)
    amb = Failure(kind=FailureKind.AMBIGUOUS, message="ask")
    assert rec.handle("a", amb) is amb
    auth = Failure(kind=FailureKind.AUTH_EXPIRED, message="login", retryable=True)
    assert rec.handle("b", auth) is auth
    no_retry = rec.handle(
        "c",
        Failure(kind=FailureKind.TRANSIENT, message="x", retryable=True),
        retry=None,
    )
    assert isinstance(no_retry, Failure)
    assert no_retry.kind == FailureKind.TRANSIENT


def test_transient_retries_exhausted() -> None:
    rec = Recovery(max_transient_retries=2)

    def retry() -> ToolResult:
        return ToolResult(
            ok=False,
            failure=Failure(kind=FailureKind.TIMEOUT, message="slow", retryable=True),
        )

    out = rec.handle(
        "t",
        Failure(kind=FailureKind.TIMEOUT, message="slow", retryable=True),
        retry=retry,
    )
    assert isinstance(out, Failure)
    assert out.kind == FailureKind.TIMEOUT
