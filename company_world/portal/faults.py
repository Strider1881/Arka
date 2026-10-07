"""Fault injection toggles for the AcmeCorp Procure portal (SPEC §2.2)."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Any

VALID_FAULTS = frozenset(
    {
        "latency",
        "flaky_500",
        "session_expiry",
        "ui_rename",
        "duplicate_submit_guard",
    }
)


def parse_faults_env(raw: str | None = None) -> set[str]:
    value = raw if raw is not None else os.environ.get("FAULTS", "")
    parts = {p.strip() for p in value.split(",") if p.strip()}
    return {p for p in parts if p in VALID_FAULTS}


@dataclass
class FaultState:
    """Process-local mutable fault configuration and counters."""

    enabled: set[str] = field(default_factory=set)
    session_expiry_n: int = 5
    # session_token -> request count (authenticated requests)
    session_request_counts: dict[str, int] = field(default_factory=dict)
    # Keys that already received a flaky 500 once: method+path+bodyhash or similar
    flaky_fired: set[str] = field(default_factory=set)
    # duplicate_submit_guard: fingerprint of successful submits
    submitted_fingerprints: set[str] = field(default_factory=set)
    # Deterministic RNG seed for tests (None = nondeterministic latency / flaky)
    rng_seed: int | None = None
    # When True, first POST per key fails once (for deterministic tests)
    flaky_test_force: bool = False

    def __post_init__(self) -> None:
        if not self.enabled:
            self.enabled = parse_faults_env()
        raw_n = os.environ.get("SESSION_EXPIRY_N")
        if raw_n:
            self.session_expiry_n = int(raw_n)

    def set_faults(self, faults: list[str] | set[str]) -> set[str]:
        self.enabled = {f for f in faults if f in VALID_FAULTS}
        return set(self.enabled)

    def enable(self, name: str) -> None:
        if name in VALID_FAULTS:
            self.enabled.add(name)

    def disable(self, name: str) -> None:
        self.enabled.discard(name)

    def is_enabled(self, name: str) -> bool:
        return name in self.enabled

    def _rng(self) -> random.Random:
        if self.rng_seed is None:
            return random.Random()
        # Advance seed slightly per call so repeated calls differ but stay reproducible
        # when tests set a fixed seed and reset state between cases.
        return random.Random(self.rng_seed)

    def maybe_latency(self) -> float:
        """Sleep 1–4s when latency fault is on. Returns seconds slept."""
        if not self.is_enabled("latency"):
            return 0.0
        delay = self._rng().uniform(1.0, 4.0)
        time.sleep(delay)
        return delay

    def maybe_flaky_500(self, key: str) -> bool:
        """Return True if this POST should fail with 500 (once per key, ~10%)."""
        if not self.is_enabled("flaky_500"):
            return False
        if key in self.flaky_fired:
            return False
        if self.flaky_test_force or self._rng().random() < 0.10:
            self.flaky_fired.add(key)
            return True
        return False

    def bump_session(self, session_id: str) -> bool:
        """
        Increment request count for session. Return True if session should expire
        (count exceeds N after this request's check — expire when count > N).
        SPEC: session invalid after N requests.
        """
        if not self.is_enabled("session_expiry"):
            return False
        count = self.session_request_counts.get(session_id, 0) + 1
        self.session_request_counts[session_id] = count
        return count > self.session_expiry_n

    def reset_session_count(self, session_id: str) -> None:
        self.session_request_counts.pop(session_id, None)

    def submit_fingerprint(
        self, vendor_id: int, invoice_number: str, amount: float, po_id: int | None
    ) -> str:
        return f"{vendor_id}|{invoice_number}|{amount:.2f}|{po_id}"

    def check_duplicate_submit(self, fingerprint: str) -> bool:
        """Return True if this is a blocked duplicate (second identical submit)."""
        if not self.is_enabled("duplicate_submit_guard"):
            return False
        return fingerprint in self.submitted_fingerprints

    def record_submit(self, fingerprint: str) -> None:
        if self.is_enabled("duplicate_submit_guard"):
            self.submitted_fingerprints.add(fingerprint)

    def ui_labels(self) -> dict[str, str]:
        """Labels/button text; ids stay stable. Renamed when ui_rename is on."""
        if self.is_enabled("ui_rename"):
            return {
                "submit_button": "Transmit document",
                "vendor": "Supplier",
                "invoice_number": "Doc #",
                "po": "Purchase ref",
                "amount": "Total due",
                "date": "Doc date",
                "attachment": "File ref",
            }
        return {
            "submit_button": "Submit invoice",
            "vendor": "Vendor",
            "invoice_number": "Invoice number",
            "po": "Purchase order",
            "amount": "Amount",
            "date": "Invoice date",
            "attachment": "Attachment name",
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": sorted(self.enabled),
            "session_expiry_n": self.session_expiry_n,
            "valid_faults": sorted(VALID_FAULTS),
        }


# Module-level singleton used by the app
fault_state = FaultState()
