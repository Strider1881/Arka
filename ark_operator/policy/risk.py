"""Map tool/action risk levels to policy decision requirements."""

from __future__ import annotations

from ark_operator.domain.enums import PolicyDecision, RiskLevel


def risk_to_decision(risk_level: str | RiskLevel) -> PolicyDecision:
    risk = RiskLevel(risk_level) if not isinstance(risk_level, RiskLevel) else risk_level
    if risk == RiskLevel.IRREVERSIBLE:
        return PolicyDecision.REQUIRE_APPROVAL
    return PolicyDecision.ALLOW
