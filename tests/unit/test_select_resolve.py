"""Select option resolution must fail closed on ambiguous substrings."""

from __future__ import annotations

from ark_operator.tools.browser import resolve_select_option

VENDORS = [
    ("1", "Northwind Supplies (ACTIVE)"),
    ("6", "Umbrella Corp (ACTIVE)"),
    ("8", "Pied Piper Cloud (BLOCKED)"),
]


def test_exact_value() -> None:
    assert resolve_select_option("6", VENDORS) == "6"


def test_observation_token() -> None:
    assert resolve_select_option("6:Umbrella Corp (ACTIVE)", VENDORS) == "6"


def test_exact_label() -> None:
    assert resolve_select_option("Umbrella Corp (ACTIVE)", VENDORS) == "6"


def test_unique_contains() -> None:
    assert resolve_select_option("Umbrella", VENDORS) == "6"


def test_ambiguous_active_suffix_fails_closed() -> None:
    # Both ACTIVE vendors contain "ACTIVE" — must not guess the first.
    assert resolve_select_option("ACTIVE", VENDORS) is None


def test_empty_fails() -> None:
    assert resolve_select_option("", VENDORS) is None
    assert resolve_select_option("9", VENDORS) is None
