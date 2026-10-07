"""Independent verifier — re-exports browser-isolated implementation (SPEC §7)."""

from ark_operator.verify.browser_verifier import BrowserVerifier, Verifier

__all__ = ["BrowserVerifier", "Verifier"]
