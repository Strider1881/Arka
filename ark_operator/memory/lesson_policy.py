"""Derive browser selector strategy from retrieved lesson *content* (not bool(lessons))."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def prefer_label_first_from_lessons(lessons: Sequence[Any]) -> bool:
    """Return True when lessons say to try labels first; False when they prefer stable ids.

    Learning AC: run2 improvement depends on applying retrieved lesson content
    (selector strategy), not merely `bool(lessons)`.
    """
    if not lessons:
        # No prior knowledge → explore labels (fails under ui_rename, then recovers).
        return True
    text = " ".join(str(x.get("lesson") if isinstance(x, dict) else x).lower() for x in lessons)
    stable_signals = (
        "stable element id",
        "#submit-invoice-button",
        "prefer stable",
        "over button text",
        "re-resolve",
    )
    label_signals = (
        "prefer label",
        "label-first",
        "try button text",
        "explore labels",
    )
    if any(s in text for s in stable_signals):
        return False
    if any(s in text for s in label_signals):
        return True
    # Unknown lesson content: do not treat mere presence as a strategy flip.
    return True


def selector_strategy_from_lessons(lessons: Sequence[Any]) -> str:
    """Human-readable strategy label for events / plan revision."""
    return "stable_id" if not prefer_label_first_from_lessons(lessons) else "label_first"
