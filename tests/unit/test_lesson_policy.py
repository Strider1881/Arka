"""Lesson content — not bool(lessons) — drives selector strategy."""

from __future__ import annotations

from ark_operator.memory.lesson_policy import (
    prefer_label_first_from_lessons,
    selector_strategy_from_lessons,
)


def test_empty_lessons_explore_labels() -> None:
    assert prefer_label_first_from_lessons([]) is True
    assert selector_strategy_from_lessons([]) == "label_first"


def test_stable_id_lesson_content() -> None:
    lessons = [
        {"lesson": ("Prefer stable element ids (#submit-invoice-button) over button text labels")}
    ]
    assert prefer_label_first_from_lessons(lessons) is False
    assert selector_strategy_from_lessons(lessons) == "stable_id"


def test_bool_lessons_alone_is_not_enough() -> None:
    # Presence of an unrelated lesson must not flip strategy.
    lessons = [{"lesson": "Record SECURITY_FINDING and continue."}]
    assert prefer_label_first_from_lessons(lessons) is True
