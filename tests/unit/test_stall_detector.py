"""Stall detector: same action + observation hash ×3 (SPEC §6.5)."""

from __future__ import annotations

from ark_operator.runtime.stall_detector import StallDetector


def test_stall_after_three_identical_pairs() -> None:
    d = StallDetector(repeat_limit=3)
    assert d.observe("click:e1", "obsA") is False
    assert d.observe("click:e1", "obsA") is False
    assert d.observe("click:e1", "obsA") is True


def test_different_obs_does_not_stall() -> None:
    d = StallDetector(repeat_limit=3)
    assert d.observe("click:e1", "a") is False
    assert d.observe("click:e1", "b") is False
    assert d.observe("click:e1", "c") is False
