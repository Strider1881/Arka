"""Domain enumerations for runs, risk, decisions, and failures."""

from enum import StrEnum


class RunState(StrEnum):
    """Orchestrator state machine states (SPEC §6.2)."""

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


TERMINAL_STATES = frozenset({RunState.COMPLETE, RunState.ESCALATED, RunState.FAILED})


class RiskLevel(StrEnum):
    READ = "READ"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    IRREVERSIBLE = "IRREVERSIBLE"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


class InvoiceDecision(StrEnum):
    SUBMIT = "submit"
    NEEDS_APPROVAL = "needs_approval"
    FLAG_DUPLICATE = "flag_duplicate"
    FLAG_MISMATCH = "flag_mismatch"
    FLAG_ASK_HUMAN = "flag_ask_human"
    REFUSE_ESCALATE = "refuse_escalate"


class FailureKind(StrEnum):
    TRANSIENT = "TRANSIENT"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    UI_CHANGED = "UI_CHANGED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    POLICY_BLOCK = "POLICY_BLOCK"
    AMBIGUOUS = "AMBIGUOUS"
    DATA_CONFLICT = "DATA_CONFLICT"
    UNRECOVERABLE = "UNRECOVERABLE"
    VALIDATION = "VALIDATION"
    TIMEOUT = "TIMEOUT"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class InvoiceOutcome(StrEnum):
    COMPLETED = "completed"
    NEEDS_ATTENTION = "needs_attention"
    REFUSED = "refused"
    FLAGGED = "flagged"
