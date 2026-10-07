"""Domain enumerations (run states, risk levels, invoice statuses, etc.).

STUB: concrete enum members land in P2+.
"""

from enum import StrEnum


class RunState(StrEnum):
    """High-level orchestrator state machine states (SPEC §6.2)."""

    INTAKE = "INTAKE"
    UNDERSTAND = "UNDERSTAND"
    CLARIFY = "CLARIFY"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    AWAIT_APPROVAL = "AWAIT_APPROVAL"
    VERIFY = "VERIFY"
    REPAIR = "REPAIR"
    REPORT = "REPORT"
    COMPLETE = "COMPLETE"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class RiskLevel(StrEnum):
    """Action risk classification for policy decisions."""

    READ = "READ"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    IRREVERSIBLE = "IRREVERSIBLE"
