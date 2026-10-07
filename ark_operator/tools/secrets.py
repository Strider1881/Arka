"""Internal secrets provider — never expose passwords to the LLM."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PortalCredentials:
    email: str
    password: str


def portal_operator_credentials() -> PortalCredentials:
    return PortalCredentials(
        email=os.environ.get("PORTAL_OPERATOR_EMAIL", "operator@acmecorp.test"),
        password=os.environ.get("PORTAL_OPERATOR_PASSWORD", "change-me"),
    )


def portal_manager_credentials() -> PortalCredentials:
    return PortalCredentials(
        email=os.environ.get("PORTAL_MANAGER_EMAIL", "priya.nair@acmecorp.test"),
        password=os.environ.get("PORTAL_MANAGER_PASSWORD", "priya-approve"),
    )


def redact_secrets(text: str, *secrets: str) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***REDACTED***")
    return out
