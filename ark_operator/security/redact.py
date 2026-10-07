"""Central secret redaction for logs, events, and tool payloads."""

from __future__ import annotations

import os
from typing import Any

_SECRET_KEYS = frozenset(
    {
        "password",
        "api_key",
        "token",
        "secret",
        "authorization",
        "anthropic_api_key",
        "session",
        "cookie",
    }
)


def active_secrets() -> list[str]:
    return [
        s
        for s in (
            os.environ.get("PORTAL_OPERATOR_PASSWORD", ""),
            os.environ.get("PORTAL_MANAGER_PASSWORD", ""),
            os.environ.get("ANTHROPIC_API_KEY", ""),
            os.environ.get("PORTAL_SESSION_SECRET", ""),
        )
        if s
    ]


def redact_text(text: str, *extra: str) -> str:
    out = text
    for secret in (*active_secrets(), *extra):
        if secret and secret in out:
            out = out.replace(secret, "***REDACTED***")
    return out


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SECRET_KEYS else redact_payload(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
