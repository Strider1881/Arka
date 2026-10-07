"""Single place for untrusted-data envelopes (SPEC §8)."""

from __future__ import annotations

import re

UNTRUSTED_START = "<<<UNTRUSTED_DATA>>>"
UNTRUSTED_END = "<<<END_UNTRUSTED_DATA>>>"

_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|SYSTEM:\s*ignore|disregard\s+(all|previous)\s+rules)",
    re.IGNORECASE,
)


def wrap_untrusted(text: str) -> str:
    """Wrap document/web text so models treat it as data, never instructions."""
    body = text.strip()
    if body.startswith(UNTRUSTED_START) and body.endswith(UNTRUSTED_END):
        return body
    return f"{UNTRUSTED_START}\n{text}\n{UNTRUSTED_END}"


def unwrap_untrusted(text: str) -> str:
    t = text.strip()
    if t.startswith(UNTRUSTED_START) and t.endswith(UNTRUSTED_END):
        return t[len(UNTRUSTED_START) : -len(UNTRUSTED_END)].strip()
    return text


def detect_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


def prepare_for_llm(text: str) -> tuple[str, bool]:
    """Return (wrapped_text, security_finding)."""
    finding = detect_injection(text)
    return wrap_untrusted(text), finding
