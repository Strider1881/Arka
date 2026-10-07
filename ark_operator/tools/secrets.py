"""Internal secrets provider — never expose passwords to the LLM."""

from __future__ import annotations

from dataclasses import dataclass

from ark_operator.config import get_settings


@dataclass(frozen=True)
class PortalCredentials:
    email: str
    password: str


def portal_operator_credentials() -> PortalCredentials:
    settings = get_settings()
    return PortalCredentials(
        email=settings.portal_operator_email,
        password=settings.portal_operator_password,
    )


def portal_manager_credentials() -> PortalCredentials:
    settings = get_settings()
    return PortalCredentials(
        email=settings.portal_manager_email,
        password=settings.portal_manager_password,
    )


def redact_secrets(text: str, *secrets: str) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***REDACTED***")
    return out
