"""LLM Settings / Haiku default / missing-key failures."""

from __future__ import annotations

import pytest
from ark_operator.config import DEFAULT_OPERATOR_MODEL, Settings, clear_settings_cache
from ark_operator.llm.anthropic_client import AnthropicClient, _normalize_structured
from ark_operator.runtime.pipeline import build_llm


def test_default_model_is_haiku() -> None:
    assert DEFAULT_OPERATOR_MODEL == "claude-haiku-5-5"


def test_anthropic_client_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    clear_settings_cache()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(api_key="")


def test_build_llm_require_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    clear_settings_cache()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_llm(require_anthropic=True)


def test_settings_reads_operator_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPERATOR_MODEL", "claude-haiku-5-5")
    clear_settings_cache()
    s = Settings()
    assert s.operator_model == "claude-haiku-5-5"


def test_normalize_structured_enum_casing() -> None:
    raw = {
        "id": "top-1",
        "steps": [
            {"id": "a", "status": "pending", "risk_level": "read"},
            {"id": "b", "status": "blocked", "risk_level": "irreversible"},
        ],
    }
    norm = _normalize_structured(raw)
    assert norm["steps"][0]["status"] == "PENDING"
    assert norm["steps"][0]["risk_level"] == "READ"
    assert norm["steps"][1]["status"] == "PENDING"
    assert norm["steps"][1]["risk_level"] == "IRREVERSIBLE"


def test_normalize_structured_string_list_objects() -> None:
    raw = {
        "permitted_actions": [
            {"action": "Submit invoice", "risk_level": "REVERSIBLE_WRITE"},
            "verify",
        ],
        "assumptions": [{"text": "Inbox is authoritative"}],
    }
    norm = _normalize_structured(raw)
    assert norm["permitted_actions"] == ["Submit invoice", "verify"]
    assert norm["assumptions"] == ["Inbox is authoritative"]
