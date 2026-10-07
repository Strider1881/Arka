"""Pydantic domain models for goals, plans, evidence, and reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ark_operator.domain.enums import (
    Confidence,
    FailureKind,
    InvoiceDecision,
    InvoiceOutcome,
    RiskLevel,
    StepStatus,
)


class Goal(BaseModel):
    text: str = Field(..., min_length=1)


class PolicyCitation(BaseModel):
    file: str
    section: str = ""
    excerpt: str = ""


class Interpretation(BaseModel):
    intended_outcome: str = ""
    assumptions: list[str] = Field(default_factory=list)
    sources_needed: list[str] = Field(default_factory=list)
    applicable_policies: list[PolicyCitation] = Field(default_factory=list)
    permitted_actions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Step(BaseModel):
    id: str
    description: str = ""
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    expected_postcondition: str = ""
    risk_level: RiskLevel = RiskLevel.READ
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    idempotency_key: str = ""
    invoice_number: str | None = None


class Plan(BaseModel):
    id: str = "plan-1"
    steps: list[Step] = Field(default_factory=list)
    revision: int = 0


class Action(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""
    risk_level: RiskLevel = RiskLevel.READ


class BrowserActionChoice(BaseModel):
    """One LLM-chosen browser action from a compact a11y observation (SPEC §6.5–6.7)."""

    action: str  # login|goto|click|fill|select|press|wait_for|done|abort
    ref: str | None = None
    text: str | None = None
    value: str | None = None
    url: str | None = None
    key: str | None = None
    rationale: str = ""


class Observation(BaseModel):
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    hash: str = ""


class Failure(BaseModel):
    kind: FailureKind
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class Approval(BaseModel):
    id: str
    run_id: str
    step_id: str = ""
    prompt: str = ""
    options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    context: dict[str, Any] = Field(default_factory=dict)
    status: str = "PENDING"  # PENDING | APPROVED | REJECTED
    decided_by: str | None = None
    decided_at: datetime | None = None


class Evidence(BaseModel):
    id: str
    label: str
    path: str = ""
    kind: str = "screenshot"
    meta: dict[str, Any] = Field(default_factory=dict)


class CriterionResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    passed: bool = False
    confidence: Confidence = Confidence.LOW
    criteria: list[CriterionResult] = Field(default_factory=list)
    overall_notes: str = ""


class InvoiceRecord(BaseModel):
    """Extracted / decided invoice unit of work."""

    invoice_number: str
    vendor: str
    amount: float
    po_number: str | None = None
    invoice_date: str = ""
    attachment_name: str = ""
    canonical_vendor: str | None = None
    decision: InvoiceDecision | None = None
    decision_reason: str = ""
    policy_citations: list[PolicyCitation] = Field(default_factory=list)
    security_finding: bool = False
    outcome: InvoiceOutcome | None = None
    portal_status: str | None = None
    confidence: Confidence = Confidence.MEDIUM
    fields_confidence: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class InvoiceLineResult(BaseModel):
    invoice_number: str
    outcome: InvoiceOutcome
    reason: str = ""
    policy_cited: list[PolicyCitation] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verified: bool = False


class RunReport(BaseModel):
    run_id: str
    summary: str = ""
    invoices: list[InvoiceLineResult] = Field(default_factory=list)
    verification: VerificationResult | None = None
    needs_attention: list[str] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    partial: bool = False
    partial_reason: str = ""


class WorkingState(BaseModel):
    """Compact derived state for LLM context (never raw event dump)."""

    run_id: str
    state: str
    goal: str = ""
    completed_steps: list[str] = Field(default_factory=list)
    pending_steps: list[str] = Field(default_factory=list)
    invoices: list[InvoiceRecord] = Field(default_factory=list)
    pending_approvals: list[str] = Field(default_factory=list)
    repair_cycles: int = 0
    notes: list[str] = Field(default_factory=list)
