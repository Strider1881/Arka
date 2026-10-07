"""LLM Settings / Haiku default / missing-key failures."""

from __future__ import annotations

import pytest
from ark_operator.config import DEFAULT_OPERATOR_MODEL, Settings
from ark_operator.llm.anthropic_client import AnthropicClient
from ark_operator.runtime.pipeline import build_llm


def test_default_model_is_haiku() -> None:
    assert DEFAULT_OPERATOR_MODEL == "claude-haiku-5-5"


def test_anthropic_client_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    # Empty key via constructor bypass still fails
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(api_key="")


def test_build_llm_require_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Clear any cached settings by constructing Settings without key
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_llm(require_anthropic=True)


def test_settings_reads_operator_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPERATOR_MODEL", "claude-haiku-5-5")
    s = Settings()
    assert s.operator_model == "claude-haiku-5-5"
