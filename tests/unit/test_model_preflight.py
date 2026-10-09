"""B2: OPERATOR_MODEL preflight fail-closed; no FakeLLM fallback on bad ids."""

from __future__ import annotations

import pytest
from ark_operator.llm.model_preflight import (
    ALLOWED_OPERATOR_MODELS,
    preflight_operator_model,
    require_valid_operator_model,
)
from ark_operator.runtime.pipeline import build_llm
from ark_operator.config import clear_settings_cache


def test_haiku_55_is_allowlisted() -> None:
    assert "claude-haiku-5-5" in ALLOWED_OPERATOR_MODELS
    ok = preflight_operator_model("claude-haiku-5-5", api_key="", probe_api=False)
    assert ok.ok


def test_unknown_model_fails_closed() -> None:
    bad = preflight_operator_model("claude-made-up-9-9", api_key="sk-test", probe_api=False)
    assert not bad.ok
    with pytest.raises(RuntimeError, match="allowlist"):
        require_valid_operator_model("claude-made-up-9-9", api_key="")


def test_build_llm_with_key_rejects_bad_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used-for-network")
    monkeypatch.setenv("OPERATOR_MODEL", "not-a-real-model")
    clear_settings_cache()
    with pytest.raises(RuntimeError, match="allowlist"):
        build_llm()
    clear_settings_cache()
