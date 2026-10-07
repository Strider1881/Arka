"""Coverage for policy.risk, decide_tool, evidence helpers."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.enums import PolicyDecision, RiskLevel
from ark_operator.policy.engine import PolicyEngine
from ark_operator.policy.risk import risk_to_decision
from ark_operator.verify.evidence import collect_evidence


def test_decide_tool_honors_rules_yaml() -> None:
    engine = PolicyEngine()
    decision, rule = engine.decide_tool("browser", RiskLevel.IRREVERSIBLE)
    assert decision == PolicyDecision.REQUIRE_APPROVAL
    assert "IRREVERSIBLE" in rule or "browser" in rule
    decision2, _ = engine.decide_tool("files", RiskLevel.READ)
    assert decision2 == PolicyDecision.ALLOW


def test_risk_to_decision() -> None:
    assert risk_to_decision(RiskLevel.IRREVERSIBLE) == PolicyDecision.REQUIRE_APPROVAL
    assert risk_to_decision("READ") == PolicyDecision.ALLOW
    assert risk_to_decision(RiskLevel.REVERSIBLE_WRITE) == PolicyDecision.ALLOW


def test_collect_evidence(tmp_path: Path) -> None:
    assert collect_evidence(tmp_path / "missing") == []
    (tmp_path / "before.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    items = collect_evidence(tmp_path)
    assert len(items) == 1
    assert items[0].kind == "screenshot"
