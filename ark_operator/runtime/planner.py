"""Typed plan generation and revision (SPEC §6.4)."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.enums import RiskLevel, StepStatus
from ark_operator.domain.models import Interpretation, InvoiceRecord, Plan, Step
from ark_operator.llm.base import LLMClient


class Planner:
    """Produces and revises Plans via LLM structured output + deterministic scaffolding."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def create_plan(self, interpretation: Interpretation) -> Plan:
        try:
            resp = self.llm.complete(
                "plan_top",
                {
                    "interpretation": interpretation.model_dump(),
                    "lessons": [],
                },
                schema=Plan,
            )
            if isinstance(resp.content, Plan):
                return resp.content
            if isinstance(resp.content, dict):
                return Plan.model_validate(resp.content)
        except Exception as exc:
            from ark_operator.llm.base import PromptNotFoundError

            # STUB only for missing FakeLLM scripts / prompt files — never swallow API errors.
            if not isinstance(exc, (PromptNotFoundError, FileNotFoundError)):
                raise
        # STUB fallback plan when LLM script/API unavailable (CI).
        steps = [
            Step(
                id="load-invoices",
                description="List and extract invoice PDFs from inbox",
                tool="files",
                args={"action": "list", "path": "company_world/inbox"},
                expected_postcondition="All invoice PDFs discovered",
                risk_level=RiskLevel.READ,
                status=StepStatus.READY,
                idempotency_key="load-invoices",
            ),
            Step(
                id="retrieve-knowledge",
                description="Retrieve applicable policies with citations",
                tool="knowledge_search",
                args={"query": "invoice processing approval tolerance vendor duplicate"},
                expected_postcondition="Policies retrieved",
                risk_level=RiskLevel.READ,
                depends_on=["load-invoices"],
                status=StepStatus.PENDING,
                idempotency_key="retrieve-knowledge",
            ),
            Step(
                id="process-invoices",
                description="Process each invoice per policy",
                tool="orchestrator",
                args={},
                expected_postcondition="Each invoice decided and acted on",
                risk_level=RiskLevel.IRREVERSIBLE,
                depends_on=["retrieve-knowledge"],
                status=StepStatus.PENDING,
                idempotency_key="process-invoices",
            ),
            Step(
                id="verify",
                description="Independent verification of portal state",
                tool="verifier",
                args={},
                expected_postcondition="VerificationResult produced",
                risk_level=RiskLevel.READ,
                depends_on=["process-invoices"],
                status=StepStatus.PENDING,
                idempotency_key="verify",
            ),
        ]
        return Plan(id="top-1", steps=steps)

    def create_invoice_subplan(self, invoice: InvoiceRecord, *, run_id: str) -> Plan:
        inv = invoice.invoice_number
        steps: list[Step] = [
            Step(
                id=f"{inv}:decide",
                description=f"Apply policy decision for {inv}",
                tool="policy",
                args={"invoice_number": inv},
                risk_level=RiskLevel.READ,
                status=StepStatus.READY,
                idempotency_key=f"{run_id}:{inv}:decide",
                invoice_number=inv,
            ),
        ]
        decision = invoice.decision.value if invoice.decision else ""
        if decision in ("submit", "needs_approval"):
            steps.append(
                Step(
                    id=f"{inv}:submit",
                    description=f"Submit {inv} via portal browser",
                    tool="browser",
                    args={"action": "submit_invoice", "invoice_number": inv},
                    risk_level=RiskLevel.IRREVERSIBLE,
                    depends_on=[f"{inv}:decide"],
                    status=StepStatus.PENDING,
                    idempotency_key=f"{run_id}:{inv}:submit",
                    invoice_number=inv,
                )
            )
        elif decision == "flag_ask_human":
            steps.append(
                Step(
                    id=f"{inv}:ask",
                    description=f"Ask human about missing PO for {inv}",
                    tool="ask_human",
                    args={"invoice_number": inv},
                    risk_level=RiskLevel.READ,
                    depends_on=[f"{inv}:decide"],
                    status=StepStatus.PENDING,
                    idempotency_key=f"{run_id}:{inv}:ask",
                    invoice_number=inv,
                )
            )
        return Plan(id=f"sub-{inv}", steps=steps, revision=0)

    def revise(self, plan: Plan, reason: str, changes: list[dict[str, Any]]) -> Plan:
        """Apply mid-run changes. Prefer plan_revision.apply_revision for contradictions."""
        from ark_operator.runtime.plan_revision import RevisionProposal, apply_revision

        proposal = RevisionProposal(
            reason=reason,
            kind="MANUAL",
            next_steps=[],
            changes=changes,
        )
        return apply_revision(plan, proposal)
