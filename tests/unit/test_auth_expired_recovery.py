"""A2: AUTH_EXPIRED recovery re-logins without retrying the stale action."""

from __future__ import annotations

from ark_operator.domain.enums import FailureKind
from ark_operator.domain.models import Failure
from ark_operator.runtime.recovery import Recovery
from ark_operator.tools.base import ToolResult


def test_auth_expired_relogin_only_when_retry_omitted() -> None:
    calls: list[str] = []

    def relogin() -> ToolResult:
        calls.append("login")
        return ToolResult(ok=True, data={"logged_in": True})

    def retry() -> ToolResult:
        calls.append("retry")
        return ToolResult(ok=True, data={"retried": True})

    rec = Recovery()
    fail = Failure(kind=FailureKind.AUTH_EXPIRED, message="session expired", retryable=True)
    out = rec.handle("k1", fail, retry=None, relogin=relogin)
    assert isinstance(out, ToolResult) and out.ok
    assert calls == ["login"]

    calls.clear()
    out2 = rec.handle("k2", fail, retry=retry, relogin=relogin)
    assert isinstance(out2, ToolResult) and out2.ok
    assert calls == ["login", "retry"]


def test_auth_expired_relogin_failure_returns_failure() -> None:
    rec = Recovery()
    fail = Failure(kind=FailureKind.AUTH_EXPIRED, message="session expired", retryable=True)

    def bad_login() -> ToolResult:
        return ToolResult(ok=False, failure=fail)

    out = rec.handle("k3", fail, retry=None, relogin=bad_login)
    assert out is fail


def test_outcome_label_fallback() -> None:
    from ark_operator.domain.enums import outcome_label

    assert outcome_label("custom_thing") == "Custom thing"
