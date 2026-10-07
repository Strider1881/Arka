"""End-to-end invoice operator pipeline (Understand → Plan → Execute → Verify → Report)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ark_operator.domain.enums import (
    InvoiceDecision,
    InvoiceOutcome,
    RiskLevel,
    RunState,
    StepStatus,
)
from ark_operator.domain.models import (
    Interpretation,
    InvoiceLineResult,
    InvoiceRecord,
    Plan,
    PolicyCitation,
    RunReport,
    Step,
    VerificationResult,
)
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.base import LLMClient
from ark_operator.llm.fake import FakeLLM
from ark_operator.memory.episodic import EpisodicMemory
from ark_operator.memory.knowledge import KnowledgeStore
from ark_operator.policy.engine import PolicyEngine
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.orchestrator import Orchestrator
from ark_operator.runtime.planner import Planner
from ark_operator.runtime.recovery import Recovery
from ark_operator.runtime.stall_detector import StallDetector
from ark_operator.runtime.understand import Understander
from ark_operator.tools.ask_human import AskHumanTool
from ark_operator.tools.browser import BrowserTool
from ark_operator.tools.files import FilesTool
from ark_operator.tools.knowledge_search import KnowledgeSearchTool
from ark_operator.tools.pdf_extract import PdfExtractTool
from ark_operator.tools.portal_api import PortalApiTool
from ark_operator.tools.registry import ToolRegistry
from ark_operator.tools.secrets import portal_operator_credentials
from ark_operator.verify.verifier import Verifier


@dataclass
class PipelineConfig:
    portal_base_url: str = "http://127.0.0.1:8765"
    inbox_dir: Path = Path("company_world/inbox")
    knowledge_dir: Path = Path("company_world/knowledge")
    data_dir: Path = Path("data")
    headless: bool = True
    auto_approve: bool | None = None  # True/False for evals; None = pause
    max_repair_cycles: int = 2
    invoice_filter: list[str] | None = None  # filename stems e.g. INV-1001


@dataclass
class PipelineResult:
    run_id: str
    state: RunState
    report: RunReport | None
    invoices: list[InvoiceRecord] = field(default_factory=list)
    verification: VerificationResult | None = None
    pending_approval_ids: list[str] = field(default_factory=list)
    steps: int = 0
    recoveries: int = 0
    failures: int = 0


class InvoicePipeline:
    """Hiring-grade narrow autonomous path for the invoice demo scenario."""

    def __init__(
        self,
        store: EventStore,
        llm: LLMClient,
        config: PipelineConfig | None = None,
        *,
        knowledge: KnowledgeStore | None = None,
        episodic: EpisodicMemory | None = None,
    ) -> None:
        self.store = store
        self.llm = llm
        self.config = config or PipelineConfig()
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge = knowledge or KnowledgeStore(self.config.data_dir / "knowledge.db")
        self.episodic = episodic or EpisodicMemory(self.config.data_dir / "episodic.db")
        self.policy = PolicyEngine()
        self.recovery = Recovery()
        self.budgets = Budgets()
        self.stall = StallDetector()
        self.understander = Understander(llm)
        self.planner = Planner(llm)
        self.registry = ToolRegistry()
        self._browser: BrowserTool | None = None
        self._portal_api: PortalApiTool | None = None

    def _setup_tools(self, run_id: str) -> None:
        creds = portal_operator_credentials()
        evidence = self.config.data_dir / "evidence" / run_id
        self._browser = BrowserTool(
            base_url=self.config.portal_base_url,
            evidence_dir=evidence,
            headless=self.config.headless,
        )
        self._portal_api = PortalApiTool(
            self.config.portal_base_url,
            email=creds.email,
            password=creds.password,
        )
        self.registry.register(FilesTool([Path("company_world").resolve(), Path.cwd()]))
        self.registry.register(PdfExtractTool())
        self.registry.register(KnowledgeSearchTool(self.knowledge))
        self.registry.register(self._portal_api)
        self.registry.register(AskHumanTool(self.store, run_id))
        self.registry.register(self._browser)

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._portal_api:
            self._portal_api.close()

    def run(self, request: str, *, run_id: str | None = None) -> PipelineResult:
        orch = Orchestrator(self.store)
        if run_id is None:
            run_id = orch.start(request)
        else:
            # resume
            pass
        self._setup_tools(run_id)
        try:
            return self._execute(run_id, request)
        finally:
            self.close()

    def resume(self, run_id: str) -> PipelineResult:
        events = self.store.list_for_run(run_id)
        goal = ""
        for ev in events:
            if ev.type == EventType.RUN_STARTED:
                goal = str(ev.payload.get("goal", ""))
                break
        self._setup_tools(run_id)
        try:
            return self._execute(run_id, goal or "Process invoices", resume=True)
        finally:
            self.close()

    def _execute(self, run_id: str, request: str, *, resume: bool = False) -> PipelineResult:
        result = PipelineResult(run_id=run_id, state=RunState.INTAKE, report=None)
        completed = self.store.completed_idempotency_keys(run_id)

        def skip(key: str) -> bool:
            return key in completed or self.store.get_idempotent(key) is not None

        # INTAKE -> UNDERSTAND
        self._state(run_id, RunState.UNDERSTAND)
        if not self.knowledge.search("invoice", top_k=1):
            self.knowledge.ingest(self.config.knowledge_dir)
        hits = self.knowledge.search("invoice approval tolerance vendor duplicate security")
        lessons = self.episodic.retrieve("portal ui fault", top_k=5)
        self.store.append(
            run_id,
            EventType.KNOWLEDGE_RETRIEVED,
            {"hits": hits, "lessons": lessons},
        )
        interpretation = self.understander.interpret(request, knowledge_snippets=hits)
        self.store.append(
            run_id,
            EventType.INTERPRETATION_CREATED,
            interpretation.model_dump(mode="json"),
        )

        # PLAN
        self._state(run_id, RunState.PLAN)
        plan = self.planner.create_plan(interpretation)
        # Apply episodic lessons: prefer stable element ids (already used)
        if lessons:
            plan = self.planner.revise(
                plan,
                "episodic lessons",
                [
                    {
                        "step_id": "process-invoices",
                        "description": "Use stable element ids; lessons applied",
                    }
                ],
            )
            self.store.append(
                run_id,
                EventType.PLAN_REVISED,
                {
                    "plan_id": plan.id,
                    "revision": plan.revision,
                    "steps": [s.model_dump(mode="json") for s in plan.steps],
                },
            )
        else:
            self.store.append(
                run_id,
                EventType.PLAN_CREATED,
                {"plan_id": plan.id, "steps": [s.model_dump(mode="json") for s in plan.steps]},
            )

        # Load portal master data for policy
        assert self._portal_api is not None
        vendors = self._portal_api.run({"action": "vendors"}).data.get("result") or []
        pos = self._portal_api.run({"action": "pos"}).data.get("result") or []
        self.policy.load_portal_master(list(vendors), list(pos))

        # EXECUTE: extract + decide + act per invoice
        self._state(run_id, RunState.EXECUTE)
        invoices = self._load_invoices(run_id, skip)
        result.invoices = invoices

        pending_approvals: list[str] = []
        for inv in invoices:
            result.steps += 1
            self.budgets.record_step()
            file_id = Path(inv.attachment_name or inv.invoice_number).stem
            inv_key = f"{run_id}:{file_id}:process"
            if skip(inv_key):
                cached = self.store.get_idempotent(inv_key) or {}
                if cached.get("decision"):
                    inv.decision = InvoiceDecision(str(cached["decision"]))
                if cached.get("outcome"):
                    inv.outcome = InvoiceOutcome(str(cached["outcome"]))
                if cached.get("reason"):
                    inv.decision_reason = str(cached["reason"])
                self.store.append(
                    run_id,
                    EventType.IDEMPOTENCY_SKIP,
                    {"idempotency_key": inv_key},
                )
                continue

            decided = self.policy.decide_invoice(inv)
            # merge decision onto inv
            inv.decision = decided.decision
            inv.decision_reason = decided.decision_reason
            inv.canonical_vendor = decided.canonical_vendor

            if inv.security_finding:
                self.store.append(
                    run_id,
                    EventType.SECURITY_FINDING,
                    {
                        "invoice_number": inv.invoice_number,
                        "file_id": file_id,
                        "pattern": "ignore previous instructions",
                    },
                )

            step_id = f"{file_id}:act"
            self.store.append(
                run_id,
                EventType.STEP_STARTED,
                {"decision": inv.decision.value if inv.decision else None},
                step_id=step_id,
            )

            outcome = self._act_on_invoice(run_id, inv, pending_approvals)
            inv.outcome = outcome
            self.store.remember_idempotent(
                inv_key,
                run_id,
                {
                    "decision": inv.decision.value if inv.decision else None,
                    "outcome": outcome.value,
                    "reason": inv.decision_reason,
                },
                step_id=step_id,
            )
            self.store.append(
                run_id,
                EventType.STEP_COMPLETED,
                {
                    "idempotency_key": inv_key,
                    "decision": inv.decision.value if inv.decision else None,
                    "outcome": outcome.value,
                },
                step_id=step_id,
            )

            if pending_approvals and self.config.auto_approve is None:
                self._state(run_id, RunState.AWAIT_APPROVAL)
                result.state = RunState.AWAIT_APPROVAL
                result.pending_approval_ids = pending_approvals
                return result

        # Auto-approve path for evals
        if pending_approvals and self.config.auto_approve is not None:
            for aid in list(pending_approvals):
                decision = "approve" if self.config.auto_approve else "reject"
                self._apply_approval(run_id, aid, decision)

        # VERIFY
        self._state(run_id, RunState.VERIFY)
        self.store.append(run_id, EventType.VERIFICATION_STARTED, {})
        assert self._portal_api is not None
        # Fresh read client for independence
        creds = portal_operator_credentials()
        verify_api = PortalApiTool(
            self.config.portal_base_url, email=creds.email, password=creds.password
        )
        try:
            verifier = Verifier(verify_api)
            verification = verifier.verify_invoices(invoices)
        finally:
            verify_api.close()
        result.verification = verification
        self.store.append(
            run_id,
            EventType.VERIFICATION_RESULT,
            verification.model_dump(mode="json"),
        )

        repair_cycles = 0
        while not verification.passed and repair_cycles < self.config.max_repair_cycles:
            self._state(run_id, RunState.REPAIR)
            repair_cycles += 1
            result.recoveries += 1
            self.store.append(
                run_id,
                EventType.RECOVERY_ATTEMPTED,
                {"cycle": repair_cycles, "notes": verification.overall_notes},
            )
            # Safe repair: re-submit invoices that should be SUBMITTED but missing
            self._repair_missing_submits(run_id, invoices)
            repair_api = PortalApiTool(
                self.config.portal_base_url, email=creds.email, password=creds.password
            )
            try:
                verification = Verifier(repair_api).verify_invoices(invoices)
            finally:
                repair_api.close()
            result.verification = verification
            self.store.append(
                run_id,
                EventType.VERIFICATION_RESULT,
                verification.model_dump(mode="json"),
            )

        # Mark outcomes from verification
        for inv in invoices:
            if inv.outcome in {InvoiceOutcome.FLAGGED, InvoiceOutcome.REFUSED}:
                continue
            if inv.decision in {InvoiceDecision.SUBMIT, InvoiceDecision.NEEDS_APPROVAL}:
                # find related criteria
                ok = verification.passed
                if not ok:
                    inv.outcome = InvoiceOutcome.NEEDS_ATTENTION
                elif inv.outcome is None:
                    inv.outcome = InvoiceOutcome.COMPLETED

        # REPORT
        self._state(run_id, RunState.REPORT)
        report = self._build_report(run_id, invoices, verification)
        result.report = report
        self.store.append(run_id, EventType.REPORT_CREATED, report.model_dump(mode="json"))
        self.episodic.distill_from_run(run_id, invoices, verification)
        self.store.append(run_id, EventType.RUN_COMPLETED, {"ok": verification.passed})
        self._state(run_id, RunState.COMPLETE)
        result.state = RunState.COMPLETE
        result.steps = self.budgets.steps
        return result

    def _state(self, run_id: str, state: RunState) -> None:
        self.store.append(run_id, EventType.STATE_CHANGED, {"state": state.value})

    def _load_invoices(self, run_id: str, skip: Any) -> list[InvoiceRecord]:
        files = self.registry.get("files")
        listed = files.run({"action": "list", "path": str(self.config.inbox_dir)})
        entries = [e for e in (listed.data.get("entries") or []) if str(e).endswith(".pdf")]
        if self.config.invoice_filter:
            allowed = set(self.config.invoice_filter)
            entries = [e for e in entries if Path(str(e)).stem in allowed]
        pdf_tool = self.registry.get("pdf_extract")
        invoices: list[InvoiceRecord] = []
        # Process in invoice number order; INV-1004 after INV-1001 for duplicate detection
        for name in sorted(entries):
            path = self.config.inbox_dir / str(name)
            key = f"{run_id}:extract:{name}"
            cached = self.store.get_idempotent(key)
            if cached and "invoice" in cached:
                invoices.append(InvoiceRecord.model_validate(cached["invoice"]))
                continue
            extracted = pdf_tool.run({"path": str(path)})
            self.store.append(
                run_id,
                EventType.TOOL_CALL,
                {"tool": "pdf_extract", "args": {"path": str(path)}},
            )
            if not extracted.ok:
                continue
            inv = InvoiceRecord.model_validate(extracted.data["invoice"])
            inv.security_finding = bool(extracted.data.get("security_finding"))
            # Never put secrets in events; raw_text is untrusted doc data only
            self.store.append(
                run_id,
                EventType.OBSERVATION,
                {
                    "invoice_number": inv.invoice_number,
                    "vendor": inv.vendor,
                    "amount": inv.amount,
                    "security_finding": inv.security_finding,
                },
            )
            self.store.remember_idempotent(key, run_id, {"invoice": inv.model_dump(mode="json")})
            invoices.append(inv)
        return invoices

    def _act_on_invoice(
        self, run_id: str, inv: InvoiceRecord, pending_approvals: list[str]
    ) -> InvoiceOutcome:
        assert inv.decision is not None
        decision = inv.decision
        if decision in {
            InvoiceDecision.FLAG_DUPLICATE,
            InvoiceDecision.FLAG_MISMATCH,
        }:
            return InvoiceOutcome.FLAGGED
        if decision == InvoiceDecision.REFUSE_ESCALATE:
            return InvoiceOutcome.REFUSED
        if decision == InvoiceDecision.FLAG_ASK_HUMAN:
            ask = self.registry.get("ask_human")
            res = ask.run(
                {
                    "prompt": (
                        f"No matching PO for {inv.invoice_number} "
                        f"({inv.vendor}, ${inv.amount}). How to proceed?"
                    ),
                    "invoice_number": inv.invoice_number,
                    "options": ["provide_po", "reject"],
                }
            )
            if self.config.auto_approve is None:
                pending_approvals.append(str(res.data["approval_id"]))
                return InvoiceOutcome.NEEDS_ATTENTION
            # evals: treat as flagged ask
            return InvoiceOutcome.FLAGGED

        clearance, rule = self.policy.clearance_for_submit(inv)
        self.store.append(
            run_id,
            EventType.TOOL_CALL,
            {"tool": "policy.clearance", "decision": clearance.value, "rule": rule},
        )
        if clearance.value == "DENY":
            self.store.append(
                run_id,
                EventType.FAILURE_CLASSIFIED,
                {"kind": "POLICY_BLOCK", "rule": rule},
            )
            return InvoiceOutcome.REFUSED

        if clearance.value == "REQUIRE_APPROVAL" or decision == InvoiceDecision.NEEDS_APPROVAL:
            ask = self.registry.get("ask_human")
            res = ask.run(
                {
                    "prompt": (
                        f"Approve invoice {inv.invoice_number} for "
                        f"{inv.canonical_vendor or inv.vendor} amounting ${inv.amount:,.2f}? "
                        f"Policy: over ${self.policy.threshold:,.0f}."
                    ),
                    "invoice_number": inv.invoice_number,
                    "amount": inv.amount,
                    "options": ["approve", "reject"],
                    "requires_portal_submit": True,
                }
            )
            aid = str(res.data["approval_id"])
            if self.config.auto_approve is True:
                self._apply_approval(run_id, aid, "approve")
                return self._browser_submit(run_id, inv)
            if self.config.auto_approve is False:
                self._apply_approval(run_id, aid, "reject")
                return InvoiceOutcome.REFUSED
            pending_approvals.append(aid)
            # Still submit to portal as PENDING_APPROVAL for demo realism when auto path off
            # Spec: create Approval and stay PENDING_APPROVAL — submit form sets that status
            return self._browser_submit(run_id, inv)

        # ALLOW submit
        return self._browser_submit(run_id, inv)

    def _browser_submit(self, run_id: str, inv: InvoiceRecord) -> InvoiceOutcome:
        browser = self.registry.get("browser")
        key = f"{run_id}:{inv.invoice_number}:submit"
        if self.store.get_idempotent(key):
            self.store.append(
                run_id,
                EventType.IDEMPOTENCY_SKIP,
                {"idempotency_key": key},
            )
            return InvoiceOutcome.COMPLETED

        def do_submit() -> Any:
            return browser.run(
                {
                    "action": "submit_invoice",
                    "vendor": inv.canonical_vendor or inv.vendor,
                    "invoice_number": inv.invoice_number,
                    "po_number": inv.po_number,
                    "amount": inv.amount,
                    "invoice_date": inv.invoice_date,
                    "attachment_name": inv.attachment_name,
                }
            )

        self.store.append(
            run_id,
            EventType.TOOL_CALL,
            {
                "tool": "browser",
                "action": "submit_invoice",
                "invoice_number": inv.invoice_number,
                "idempotency_key": key,
            },
        )
        res = do_submit()
        if not res.ok and res.failure is not None:
            recovered = self.recovery.handle(
                key,
                res.failure,
                retry=do_submit,
                relogin=lambda: browser.run({"action": "login"}),
            )
            from ark_operator.tools.base import ToolResult as TR

            if isinstance(recovered, TR):
                res = recovered
            else:
                self.store.append(
                    run_id,
                    EventType.FAILURE_CLASSIFIED,
                    recovered.model_dump(mode="json"),
                )
                return InvoiceOutcome.NEEDS_ATTENTION

        self.store.append(
            run_id,
            EventType.OBSERVATION,
            {
                "ok": res.ok,
                "url": (res.data or {}).get("url"),
                "banner": (res.data or {}).get("banner"),
            },
        )
        self.store.remember_idempotent(key, run_id, {"ok": res.ok})
        if res.ok:
            return (
                InvoiceOutcome.COMPLETED
                if inv.decision == InvoiceDecision.SUBMIT
                else InvoiceOutcome.NEEDS_ATTENTION  # pending approval in portal
            )
        return InvoiceOutcome.NEEDS_ATTENTION

    def _apply_approval(self, run_id: str, approval_id: str, decision: str) -> None:
        info = self.store.decide_approval(approval_id, decision, decided_by="eval-auto")
        self.store.append(
            run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": approval_id, "decision": decision, "info": info},
        )

    def _repair_missing_submits(self, run_id: str, invoices: list[InvoiceRecord]) -> None:
        for inv in invoices:
            if inv.decision not in {InvoiceDecision.SUBMIT, InvoiceDecision.NEEDS_APPROVAL}:
                continue
            api = self.registry.get("portal_api")
            found = api.run({"action": "invoice_by_number", "invoice_number": inv.invoice_number})
            if found.ok and found.data.get("result"):
                continue
            self._browser_submit(run_id, inv)

    def _build_report(
        self,
        run_id: str,
        invoices: list[InvoiceRecord],
        verification: VerificationResult,
    ) -> RunReport:
        lines: list[InvoiceLineResult] = []
        needs: list[str] = []
        security: list[str] = []
        for inv in invoices:
            outcome = inv.outcome or InvoiceOutcome.NEEDS_ATTENTION
            verified = False
            if outcome == InvoiceOutcome.COMPLETED and verification.passed:
                verified = True
            if outcome in {InvoiceOutcome.NEEDS_ATTENTION, InvoiceOutcome.FLAGGED}:
                needs.append(inv.invoice_number)
            if inv.security_finding:
                security.append(inv.invoice_number)
            lines.append(
                InvoiceLineResult(
                    invoice_number=inv.invoice_number,
                    outcome=outcome,
                    reason=inv.decision_reason,
                    policy_cited=[
                        PolicyCitation(file="invoice_processing_sop.md", section="Outcomes")
                    ],
                    verified=verified,
                )
            )
        summary = (
            f"Processed {len(invoices)} invoices. "
            f"Verified={'yes' if verification.passed else 'no'} "
            f"({verification.overall_notes})."
        )
        return RunReport(
            run_id=run_id,
            summary=summary,
            invoices=lines,
            verification=verification,
            needs_attention=needs,
            security_findings=security,
        )


def build_default_fake_llm() -> FakeLLM:
    """Scripts sufficient for CI understand/plan without Anthropic."""
    return FakeLLM(
        scripts={
            "understand": Interpretation(
                intended_outcome="Process pending vendor invoices with policy and proof",
                assumptions=["Inbox PDFs are authoritative", "Portal is AcmeCorp Procure"],
                sources_needed=["inbox", "knowledge", "portal"],
                applicable_policies=[
                    PolicyCitation(file="invoice_processing_sop.md", section="Three-way match")
                ],
                permitted_actions=["extract", "submit", "ask_human", "verify"],
                success_criteria=["Portal matches decisions", "Verifier passes"],
                open_questions=[],
            ),
            "plan_top": lambda _vars: Plan(
                id="top-1",
                steps=[
                    Step(
                        id="load-invoices",
                        description="Load invoices",
                        tool="files",
                        status=StepStatus.READY,
                        risk_level=RiskLevel.READ,
                    )
                ],
            ),
        }
    )
