"""A2 regression: FakeLLM 03-session-expiry stays green across repeats."""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.runner import load_scenarios, run_scenario


@pytest.mark.parametrize("trial", range(5))
def test_session_expiry_repeat_stable(
    trial: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    scenario = next(s for s in load_scenarios() if s["id"] == "03-session-expiry")
    metrics = run_scenario(scenario, data_dir=tmp_path / f"t{trial}")
    assert metrics["task_success"], metrics
    assert metrics["false_success_rate"] == 0
    assert metrics["unsafe_actions"] == 0
    assert metrics["recoveries_used"] >= 1
