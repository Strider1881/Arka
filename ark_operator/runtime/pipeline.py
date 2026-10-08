"""End-to-end invoice operator pipeline (Understand → Plan → Execute → Verify → Report)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ark_operator.domain.enums import (
    FailureKind,
    InvoiceDecision,
    InvoiceOutcome,
    RiskLevel,
    RunState,
    StepStatus,
)
from ark_operator.domain.models import (
    Failure,
    Interpretation,
    InvoiceLineResult,
    InvoiceRecord,
    Plan,
    PolicyCitation,
    RunReport,
    Step,
    VerificationResult,
)
from ark_operator.events.replay import fold_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.base import LLMClient
from ark_operator.llm.fake import FakeLLM
from ark_operator.llm.usage_logger import UsageLoggingLLM
from ark_operator.memory.episodic import EpisodicMemory
from ark_operator.memory.knowledge import KnowledgeStore
from ark_operator.memory.lesson_policy import (
    prefer_label_first_from_lessons,
    selector_strategy_from_lessons,
)
from ark_operator.policy.engine import PolicyEngine
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.fsm import StateMachine
from ark_operator.runtime.idempotency import IrreversibleLedger, irreversible_key
from ark_operator.runtime.orchestrator import Orchestrator
from ark_operator.runtime.plan_revision import (
    AUTH_EXPIRED,
    Contradiction,
    apply_revision,
    browser_prefs_from_plan,
    detect_from_browser_observation,
    detect_missing_po,
    propose_revision,
    revision_event_payload,
)
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
from ark_operator.verify.evidence import collect_run_evidence
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
    # Test/eval hook: stop after N invoices before VERIFY (crash/resume AC).
    crash_after_invoices: int | None = None
    # None/True = a11y observe→act loop (default measured path). False = RPA shortcut.
    use_browser_loop: bool | None = True
    # After verifier miss, optionally heal via submit_invoice RPA shortcut.
    # Default False: a11y measured path (make eval / eval-llm) must not silent-heal.
    # Enable only for make eval-rpa (shortcut path) when needed.
    allow_rpa_repair: bool = False
    # Enter CLARIFY when Interpretation.open_questions is non-empty (scenario 11).
    force_clarify: bool = False


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
        self._raw_llm = llm
        self.llm = llm
        self.understander = Understander(llm)
        self.planner = Planner(llm)
        self.registry = ToolRegistry()
        self._browser: BrowserTool | None = None
        self._portal_api: PortalApiTool | None = None
        self._plan: Plan | None = None
        self._invoice_subplan: Plan | None = None
        self._recovery_count = 0
        # Runtime prefs consumed from PLAN_REVISED step args (prefer_stable_ids, …).
        self._plan_browser_prefs: dict[str, Any] = {}

    def _setup_tools(self, run_id: str, *, prefer_label_first: bool = False) -> None:
        creds = portal_operator_credentials()
        evidence = self.config.data_dir / "evidence" / run_id
        self._browser = BrowserTool(
            base_url=self.config.portal_base_url,
            evidence_dir=evidence,
            headless=self.config.headless,
            prefer_label_first=prefer_label_first,
        )
        self._portal_api = PortalApiTool(
            self.config.portal_base_url,
            email=creds.email,
            password=creds.password,
        )
        self.registry = ToolRegistry()
        # Sandbox: company_world only (never Path.cwd() — would expose .env).
        self.registry.register(FilesTool([Path("company_world").resolve()]))
        self.registry.register(PdfExtractTool(llm=self.llm))
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
        # Orchestrator owns run_id allocation only; InvoicePipeline owns phases (single runtime).
        orch = Orchestrator(self.store)
        if run_id is None:
            run_id = orch.start(request)
        lessons = self.episodic.retrieve("portal_ui", top_k=5)
        prefer = prefer_label_first_from_lessons(lessons)
        self._setup_tools(run_id, prefer_label_first=prefer)
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
        lessons = self.episodic.retrieve("portal_ui", top_k=5)
        prefer = prefer_label_first_from_lessons(lessons)
        self._setup_tools(run_id, prefer_label_first=prefer)
        try:
            return self._execute(run_id, goal or "Process invoices", resume=True)
        finally:
            self.close()

    def _execute(self, run_id: str, request: str, *, resume: bool = False) -> PipelineResult:
        result = PipelineResult(run_id=run_id, state=RunState.INTAKE, report=None)
        snapshot = fold_run(self.store, run_id)
        fsm = StateMachine.from_fold(self.store, run_id, snapshot.state)
        ledger = IrreversibleLedger(self.store, run_id)
        # Rebuild duplicate detection purely from folded events.
        self.policy.seen_keys |= set(snapshot.seen_duplicate_keys)
        # Log every LLM call's tokens/cost onto the event timeline (Details).
        self.llm = UsageLoggingLLM(self._raw_llm, self.store, run_id, self.budgets)
        self.understander = Understander(self.llm)
        self.planner = Planner(self.llm)

        def is_terminal(key: str) -> bool:
            cached = self.store.get_idempotent(key)
            return bool(cached and cached.get("terminal"))

        def go(next_state: RunState) -> None:
            fsm.transition(next_state)
            result.state = fsm.state

        # Advance toward EXECUTE via legal transitions only.
        if fsm.state == RunState.INTAKE:
            go(RunState.UNDERSTAND)
        if fsm.state == RunState.UNDERSTAND:
            if not self.knowledge.search("invoice", top_k=1):
                self.knowledge.ingest(self.config.knowledge_dir)
            hits = self.knowledge.search("invoice approval tolerance vendor duplicate security")
            lessons = self.episodic.retrieve("portal_ui", top_k=5)
            self.store.append(
                run_id,
                EventType.KNOWLEDGE_RETRIEVED,
                {
                    "hits": [
                        {
                            "file": h.get("file"),
                            "heading": h.get("heading"),
                            "score": h.get("score"),
                        }
                        for h in hits
                    ],
                    "lessons": lessons,
                },
            )
            interpretation = self.understander.interpret(request, knowledge_snippets=hits)
            self.store.append(
                run_id,
                EventType.INTERPRETATION_CREATED,
                interpretation.model_dump(mode="json"),
            )
            # CLARIFY: consequential open questions (scenario 11 / force_clarify).
            if interpretation.open_questions or self.config.force_clarify:
                go(RunState.CLARIFY)
                q = (
                    interpretation.open_questions[0]
                    if interpretation.open_questions
                    else "Blocked on a consequential open question before planning."
                )
                ask = self.registry.get("ask_human")
                res = ask.run(
                    {
                        "prompt": q,
                        "invoice_number": "CLARIFY",
                        "file_id": "clarify",
                        "options": ["proceed_with_assumptions", "reject"],
                        "risk": RiskLevel.READ.value,
                        "requires_portal_submit": False,
                        "reason": "open_question",
                    }
                )
                aid = str(res.data["approval_id"])
                if self.config.auto_approve is True:
                    self._apply_approval(run_id, aid, "approve")
                    go(RunState.PLAN)
                elif self.config.auto_approve is False:
                    self._apply_approval(run_id, aid, "reject")
                    go(RunState.PLAN)
                else:
                    go(RunState.AWAIT_APPROVAL)
                    result.pending_approval_ids = [aid]
                    return result
            else:
                go(RunState.PLAN)
        else:
            hits = self.knowledge.search("invoice approval tolerance vendor duplicate security")
            if not hits:
                self.knowledge.ingest(self.config.knowledge_dir)
                hits = self.knowledge.search("invoice approval tolerance vendor duplicate security")
            lessons = self.episodic.retrieve("portal_ui", top_k=5)
            interpretation = self.understander.interpret(request, knowledge_snippets=hits)

        # PLAN
        if fsm.state == RunState.PLAN:
            plan = self.planner.create_plan(interpretation)
            self.store.append(
                run_id,
                EventType.PLAN_CREATED,
                {
                    "plan_id": plan.id,
                    "steps": [s.model_dump(mode="json") for s in plan.steps],
                },
            )
            if lessons and not prefer_label_first_from_lessons(lessons):
                # Lesson *content* prefers stable ids → structural submit args change.
                from ark_operator.runtime.plan_revision import UI_RENAME

                lesson_c = Contradiction(
                    kind=UI_RENAME,
                    reason=(
                        "Retrieved lesson content prefers stable element ids "
                        f"({selector_strategy_from_lessons(lessons)})."
                    ),
                    evidence={"lessons": [str(x.get("lesson") or x) for x in lessons[:3]]},
                )
                proposal = propose_revision(plan, lesson_c)
                plan = apply_revision(plan, proposal)
                self.store.append(
                    run_id,
                    EventType.PLAN_REVISED,
                    revision_event_payload(plan, proposal),
                )
                self._apply_plan_browser_prefs(plan)
            self._plan = plan
            go(RunState.EXECUTE)
        elif fsm.state == RunState.AWAIT_APPROVAL:
            # Clarify pause happens before PLAN; approval pause happens mid-EXECUTE.
            has_plan = any(
                e.type == EventType.PLAN_CREATED for e in self.store.list_for_run(run_id)
            )
            if not has_plan:
                go(RunState.PLAN)
                plan = self.planner.create_plan(interpretation)
                self.store.append(
                    run_id,
                    EventType.PLAN_CREATED,
                    {
                        "plan_id": plan.id,
                        "steps": [s.model_dump(mode="json") for s in plan.steps],
                    },
                )
                self._plan = plan
                go(RunState.EXECUTE)
            else:
                go(RunState.EXECUTE)
        elif fsm.state != RunState.EXECUTE:
            # Mid-VERIFY/REPAIR resume: continue from VERIFY below
            pass

        # Load portal master data for policy (fail closed if POs missing).
        assert self._portal_api is not None
        vendors_res = self._portal_api.run({"action": "vendors"})
        pos_res = self._portal_api.run({"action": "pos"})
        if not vendors_res.ok or not pos_res.ok:
            vendors_res = self._portal_api.run({"action": "vendors"})
            pos_res = self._portal_api.run({"action": "pos"})
        vendors = list(vendors_res.data.get("result") or []) if vendors_res.ok else []
        pos = list(pos_res.data.get("result") or []) if pos_res.ok else []
        if not pos:
            detail = {
                "vendors_ok": vendors_res.ok,
                "pos_ok": pos_res.ok,
                "vendors_n": len(vendors),
                "pos_n": len(pos),
                "vendors_err": (vendors_res.failure.message if vendors_res.failure else None),
                "pos_err": pos_res.failure.message if pos_res.failure else None,
            }
            self.store.append(
                run_id,
                EventType.FAILURE_CLASSIFIED,
                {
                    "kind": "UNRECOVERABLE",
                    "message": "portal master data unavailable",
                    **detail,
                },
            )
            report = self._build_report(
                run_id,
                [],
                VerificationResult(
                    passed=False,
                    overall_notes="portal master data unavailable",
                ),
                partial=True,
                partial_reason="portal master data unavailable",
            )
            result.report = report
            self.store.append(run_id, EventType.REPORT_CREATED, report.model_dump(mode="json"))
            self.store.append(
                run_id,
                EventType.RUN_FAILED,
                {"reason": "portal_master_unavailable", **detail},
            )
            go(RunState.FAILED)
            result.state = RunState.FAILED
            return result
        self.policy.load_portal_master(vendors, pos)

        # EXECUTE
        if fsm.state == RunState.EXECUTE:
            invoices = self._load_invoices(run_id)
            result.invoices = invoices
            pending_approvals: list[str] = []
            processed = 0
            for inv in invoices:
                result.steps += 1
                self.budgets.record_step()
                file_id = Path(inv.attachment_name or inv.invoice_number).stem
                inv_key = f"{run_id}:{file_id}:process"
                if is_terminal(inv_key):
                    cached = self.store.get_idempotent(inv_key) or {}
                    if cached.get("decision"):
                        inv.decision = InvoiceDecision(str(cached["decision"]))
                    if cached.get("outcome"):
                        inv.outcome = InvoiceOutcome(str(cached["outcome"]))
                    if cached.get("reason"):
                        inv.decision_reason = str(cached["reason"])
                    if cached.get("canonical_vendor"):
                        inv.canonical_vendor = str(cached["canonical_vendor"])
                    self.policy.remember_seen(inv)
                    self.store.append(
                        run_id,
                        EventType.IDEMPOTENCY_SKIP,
                        {"idempotency_key": inv_key, "irreversible": False},
                    )
                    processed += 1
                    continue

                budget_status = self.budgets.check()
                if budget_status == "warning":
                    self.budgets.mark_warned()
                    self.store.append(
                        run_id,
                        EventType.BUDGET_WARNING,
                        {"ratios": self.budgets.ratios()},
                    )
                if budget_status == "exhausted":
                    report = self._build_report(
                        run_id,
                        invoices,
                        VerificationResult(passed=False, overall_notes="budget exhausted"),
                        partial=True,
                        partial_reason="budget exhausted",
                    )
                    result.report = report
                    self.store.append(
                        run_id, EventType.REPORT_CREATED, report.model_dump(mode="json")
                    )
                    self.store.append(
                        run_id,
                        EventType.RUN_COMPLETED,
                        {"ok": False, "partial": True, "reason": "budget exhausted"},
                    )
                    go(RunState.REPORT)
                    go(RunState.COMPLETE)
                    result.steps = self.budgets.steps
                    return result

                decided = self.policy.decide_invoice(inv)
                inv.decision = decided.decision
                inv.decision_reason = decided.decision_reason
                inv.canonical_vendor = decided.canonical_vendor
                inv.policy_citations = list(decided.policy_citations)
                self.policy.remember_seen(inv)

                # Hierarchical plan: per-invoice sub-plan drives execution steps.
                sub = self.planner.create_invoice_subplan(inv, run_id=run_id)
                self._invoice_subplan = sub
                self.store.append(
                    run_id,
                    EventType.PLAN_CREATED,
                    {
                        "plan_id": sub.id,
                        "kind": "invoice_subplan",
                        "invoice_number": inv.invoice_number,
                        "file_id": file_id,
                        "decision": inv.decision.value if inv.decision else None,
                        "steps": [s.model_dump(mode="json") for s in sub.steps],
                    },
                )
                # Observation: missing PO contradicts three-way-match assumption.
                miss = detect_missing_po(
                    invoice_number=inv.invoice_number,
                    po_number=inv.po_number,
                    decision=inv.decision.value if inv.decision else None,
                )
                if miss is not None:
                    self._emit_plan_revision(run_id, miss, base_plan=sub)

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

                outcome = self._act_on_invoice(run_id, inv, pending_approvals, ledger, subplan=sub)
                inv.outcome = outcome

                if pending_approvals and self.config.auto_approve is None:
                    go(RunState.AWAIT_APPROVAL)
                    result.pending_approval_ids = list(pending_approvals)
                    return result

                self.store.remember_idempotent(
                    inv_key,
                    run_id,
                    {
                        "terminal": True,
                        "decision": inv.decision.value if inv.decision else None,
                        "outcome": outcome.value,
                        "reason": inv.decision_reason,
                        "canonical_vendor": inv.canonical_vendor,
                        "invoice_number": inv.invoice_number,
                        "policy_citations": [
                            c.model_dump(mode="json") for c in inv.policy_citations
                        ],
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
                        "canonical_vendor": inv.canonical_vendor,
                        "invoice_number": inv.invoice_number,
                        "irreversible": False,
                        "ok": True,
                    },
                    step_id=step_id,
                )
                processed += 1

                if (
                    self.config.crash_after_invoices is not None
                    and processed >= self.config.crash_after_invoices
                    and not resume
                ):
                    result.state = RunState.EXECUTE
                    return result

            go(RunState.VERIFY)
        else:
            invoices = result.invoices or self._load_invoices(run_id)
            result.invoices = invoices

        # VERIFY — always a fresh Playwright context (never shares executor cookies).
        if fsm.state == RunState.VERIFY:
            self.store.append(run_id, EventType.VERIFICATION_STARTED, {})
            evidence = self.config.data_dir / "verify-evidence" / run_id
            verifier = Verifier(
                self.config.portal_base_url,
                evidence_dir=evidence,
                headless=self.config.headless,
            )
            try:
                verification = verifier.verify_invoices(invoices)
            finally:
                verifier.close()
            result.verification = verification
            self.store.append(
                run_id,
                EventType.VERIFICATION_RESULT,
                verification.model_dump(mode="json"),
            )

            repair_cycles = 0
            while not verification.passed and repair_cycles < self.config.max_repair_cycles:
                go(RunState.REPAIR)
                repair_cycles += 1
                result.recoveries += 1
                self.store.append(
                    run_id,
                    EventType.RECOVERY_ATTEMPTED,
                    {"cycle": repair_cycles, "notes": verification.overall_notes},
                )
                self._repair_missing_submits(run_id, invoices, ledger)
                go(RunState.EXECUTE)
                go(RunState.VERIFY)
                verifier2 = Verifier(
                    self.config.portal_base_url,
                    evidence_dir=evidence / f"repair-{repair_cycles}",
                    headless=self.config.headless,
                )
                try:
                    verification = verifier2.verify_invoices(invoices)
                finally:
                    verifier2.close()
                result.verification = verification
                self.store.append(
                    run_id,
                    EventType.VERIFICATION_RESULT,
                    verification.model_dump(mode="json"),
                )

            for inv in invoices:
                if inv.outcome in {InvoiceOutcome.FLAGGED, InvoiceOutcome.REFUSED}:
                    continue
                if inv.decision == InvoiceDecision.SUBMIT:
                    inv.outcome = (
                        InvoiceOutcome.COMPLETED
                        if verification.passed
                        else InvoiceOutcome.NEEDS_ATTENTION
                    )
                elif inv.decision == InvoiceDecision.NEEDS_APPROVAL:
                    if not verification.passed:
                        inv.outcome = InvoiceOutcome.NEEDS_ATTENTION

            go(RunState.REPORT)
        else:
            assert result.verification is not None
            verification = result.verification

        # REPORT
        report = self._build_report(run_id, invoices, verification)
        result.report = report
        self.store.append(run_id, EventType.REPORT_CREATED, report.model_dump(mode="json"))
        recoveries = [
            dict(ev.payload)
            for ev in self.store.list_for_run(run_id)
            if ev.type == EventType.RECOVERY_ATTEMPTED
        ]
        result.recoveries = max(result.recoveries, len(recoveries))
        self.episodic.distill_from_run(run_id, invoices, verification, recoveries=recoveries)
        self.store.append(run_id, EventType.RUN_COMPLETED, {"ok": verification.passed})
        go(RunState.COMPLETE)
        result.steps = self.budgets.steps
        return result

    def _load_invoices(self, run_id: str) -> list[InvoiceRecord]:
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
            # Never put secrets or full PDF text in events
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

    def _approval_status_for(self, run_id: str, inv: InvoiceRecord) -> str | None:
        """Return APPROVED/REJECTED/PENDING if an approval exists for this invoice."""
        file_id = Path(inv.attachment_name or inv.invoice_number).stem
        latest: str | None = None
        for ev in self.store.list_for_run(run_id):
            if ev.type != EventType.APPROVAL_REQUESTED:
                continue
            ctx = ev.payload.get("context") or {}
            if ctx.get("invoice_number") == inv.invoice_number or ctx.get("file_id") == file_id:
                aid = str(ev.payload.get("approval_id"))
                got = self.store.get_approval(aid)
                if got:
                    latest = str(got.get("status") or "PENDING")
        return latest

    def _act_on_invoice(
        self,
        run_id: str,
        inv: InvoiceRecord,
        pending_approvals: list[str],
        ledger: IrreversibleLedger,
        *,
        subplan: Plan | None = None,
    ) -> InvoiceOutcome:
        """Execute from the latest invoice sub-plan step queue (plans drive browser work)."""
        assert inv.decision is not None
        decision = inv.decision
        file_id = Path(inv.attachment_name or inv.invoice_number).stem
        plan = subplan or self._invoice_subplan

        # Walk fold-derived / latest sub-plan steps; policy-only steps mark flags/refuses.
        if plan is not None:
            for step in plan.steps:
                tool = (step.tool or "").lower()
                if tool in {"policy", ""} and step.id.endswith(":decide"):
                    continue
                if tool == "ask_human" or step.id.endswith(":ask"):
                    return self._ask_human_for_invoice(
                        run_id, inv, pending_approvals, file_id, kind="missing_po"
                    )
                if tool == "browser" or step.id.endswith(":submit"):
                    return self._submit_with_clearance(
                        run_id, inv, pending_approvals, ledger, file_id
                    )

        # Fallback when sub-plan has no action steps (flag/refuse).
        if decision in {
            InvoiceDecision.FLAG_DUPLICATE,
            InvoiceDecision.FLAG_MISMATCH,
        }:
            return InvoiceOutcome.FLAGGED
        if decision == InvoiceDecision.REFUSE_ESCALATE:
            return InvoiceOutcome.REFUSED
        if decision == InvoiceDecision.FLAG_ASK_HUMAN:
            return self._ask_human_for_invoice(
                run_id, inv, pending_approvals, file_id, kind="missing_po"
            )
        return self._submit_with_clearance(run_id, inv, pending_approvals, ledger, file_id)

    def _ask_human_for_invoice(
        self,
        run_id: str,
        inv: InvoiceRecord,
        pending_approvals: list[str],
        file_id: str,
        *,
        kind: str,
    ) -> InvoiceOutcome:
        status = self._approval_status_for(run_id, inv)
        if status == "APPROVED":
            return InvoiceOutcome.FLAGGED
        if status == "REJECTED":
            return InvoiceOutcome.REFUSED
        if status == "PENDING" or self.config.auto_approve is None:
            if status != "PENDING":
                ask = self.registry.get("ask_human")
                res = ask.run(self._human_prompt(inv, file_id, kind=kind))
                pending_approvals.append(str(res.data["approval_id"]))
            else:
                for row in self.store.pending_approvals(run_id):
                    pending_approvals.append(str(row["id"]))
            if self.config.auto_approve is None:
                return InvoiceOutcome.NEEDS_ATTENTION
        if self.config.auto_approve is not None:
            # Seeded eval path still creates APPROVAL_REQUESTED for scoring honesty.
            if status not in {"APPROVED", "REJECTED", "PENDING"}:
                ask = self.registry.get("ask_human")
                res = ask.run(self._human_prompt(inv, file_id, kind=kind))
                decision = "approve" if self.config.auto_approve else "reject"
                self._apply_approval(run_id, str(res.data["approval_id"]), decision)
            return InvoiceOutcome.FLAGGED if kind == "missing_po" else InvoiceOutcome.REFUSED
        return InvoiceOutcome.NEEDS_ATTENTION

    def _submit_with_clearance(
        self,
        run_id: str,
        inv: InvoiceRecord,
        pending_approvals: list[str],
        ledger: IrreversibleLedger,
        file_id: str,
    ) -> InvoiceOutcome:
        decision = inv.decision
        assert decision is not None
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
            status = self._approval_status_for(run_id, inv)
            if status == "APPROVED" or self.config.auto_approve is True:
                if status != "APPROVED":
                    ask = self.registry.get("ask_human")
                    res = ask.run(self._human_prompt(inv, file_id, kind="over_threshold"))
                    self._apply_approval(run_id, str(res.data["approval_id"]), "approve")
                return self._browser_submit(run_id, inv, ledger)
            if status == "REJECTED" or self.config.auto_approve is False:
                if status != "REJECTED":
                    ask = self.registry.get("ask_human")
                    res = ask.run(self._human_prompt(inv, file_id, kind="over_threshold"))
                    self._apply_approval(run_id, str(res.data["approval_id"]), "reject")
                return InvoiceOutcome.REFUSED
            if status != "PENDING":
                ask = self.registry.get("ask_human")
                res = ask.run(self._human_prompt(inv, file_id, kind="over_threshold"))
                pending_approvals.append(str(res.data["approval_id"]))
            else:
                for row in self.store.pending_approvals(run_id):
                    pending_approvals.append(str(row["id"]))
            return InvoiceOutcome.NEEDS_ATTENTION

        return self._browser_submit(run_id, inv, ledger)

    def _human_prompt(self, inv: InvoiceRecord, file_id: str, *, kind: str) -> dict[str, Any]:
        """Approval/question payload with summary, policy, and risk for the UI card."""
        citations = [c.model_dump(mode="json") for c in inv.policy_citations]
        vendor = inv.canonical_vendor or inv.vendor
        if kind == "missing_po":
            prompt = (
                f"No matching PO for {inv.invoice_number} "
                f"({vendor}, ${inv.amount:,.2f}). How to proceed?"
            )
            options = ["provide_po", "reject"]
            risk = RiskLevel.READ.value
            requires_submit = False
        else:
            prompt = (
                f"Approve invoice {inv.invoice_number} for {vendor} amounting "
                f"${inv.amount:,.2f}? Policy: over ${self.policy.threshold:,.0f}."
            )
            options = ["approve", "reject"]
            risk = RiskLevel.IRREVERSIBLE.value
            requires_submit = True
            if not citations:
                citations = [
                    {
                        "file": "approval_policy.md",
                        "section": "Threshold",
                        "excerpt": f">${self.policy.threshold:,.0f} needs manager approval",
                    }
                ]
        return {
            "prompt": prompt,
            "invoice_number": inv.invoice_number,
            "file_id": file_id,
            "vendor": vendor,
            "amount": inv.amount,
            "po_number": inv.po_number,
            "decision": inv.decision.value if inv.decision else None,
            "reason": inv.decision_reason,
            "risk": risk,
            "policy_cited": citations,
            "options": options,
            "requires_portal_submit": requires_submit,
        }

    def _use_browser_loop(self) -> bool:
        """Default measured path is a11y loop; set use_browser_loop=False for RPA shortcut."""
        if self.config.use_browser_loop is not None:
            return bool(self.config.use_browser_loop)
        return True

    def _browser_submit(
        self, run_id: str, inv: InvoiceRecord, ledger: IrreversibleLedger
    ) -> InvoiceOutcome:
        key = irreversible_key(run_id, inv.invoice_number, "submit")
        # Exactly-once: never re-submit a committed irreversible write.
        if ledger.is_committed(key):
            self.store.append(
                run_id,
                EventType.IDEMPOTENCY_SKIP,
                {"idempotency_key": key, "irreversible": True},
            )
            return InvoiceOutcome.NEEDS_ATTENTION

        fields = {
            "vendor": inv.canonical_vendor or inv.vendor,
            "invoice_number": inv.invoice_number,
            "po_number": inv.po_number,
            "amount": inv.amount,
            "invoice_date": inv.invoice_date,
            "attachment_name": inv.attachment_name,
        }
        if self._use_browser_loop():
            return self._browser_submit_loop(run_id, inv, ledger, key, fields)
        return self._browser_submit_shortcut(run_id, inv, ledger, key, fields)

    def _browser_submit_loop(
        self,
        run_id: str,
        inv: InvoiceRecord,
        ledger: IrreversibleLedger,
        key: str,
        fields: dict[str, Any],
    ) -> InvoiceOutcome:
        """One a11y action at a time (SPEC §6.5–6.7) via Executor + BrowserLoop."""
        from ark_operator.runtime.executor import Executor

        prefer_label = self._effective_prefer_label_first()
        prefs = self._plan_browser_prefs
        relogin = bool(prefs.get("relogin_on_auth_expired", True))
        recover_page = bool(prefs.get("recover_wrong_page", True))
        recover_goto = str(prefs.get("recover_goto") or "/invoices/submit")
        executor = Executor(
            self.store,
            self.registry,
            self.policy,
            self.recovery,
            self.stall,
            run_id,
            llm=self.llm,
            budgets=self.budgets,
        )
        self.store.append(
            run_id,
            EventType.TOOL_CALL,
            {
                "tool": "browser",
                "action": "a11y_loop",
                "invoice_number": inv.invoice_number,
                "idempotency_key": key,
                "prefer_label_first": prefer_label,
                "plan_prefs": dict(prefs),
            },
        )
        loop_res = executor.run_browser_submit(
            fields,
            step_id=f"{inv.invoice_number}:submit",
            idempotency_key=key,
            prefer_label_first=prefer_label,
            relogin_on_auth_expired=relogin,
            recover_wrong_page=recover_page,
            recover_goto=recover_goto,
        )
        if loop_res.recovered_from_label:
            self._recovery_count += 1
            # Ensure scoring sees UI recovery even if loop already logged one.
            if not any(
                e.type == EventType.RECOVERY_ATTEMPTED
                and (e.payload or {}).get("kind") == "UI_CHANGED"
                for e in self.store.list_for_run(run_id)[-20:]
            ):
                self.store.append(
                    run_id,
                    EventType.RECOVERY_ATTEMPTED,
                    {
                        "kind": "UI_CHANGED",
                        "detail": (
                            "label/role miss → re-observe a11y and re-choose via browser_step"
                        ),
                        "idempotency_key": key,
                    },
                )
        evidence_ids = list(loop_res.data.get("evidence") or [])
        inv.evidence_ids = evidence_ids
        for eid in evidence_ids:
            self.store.append(
                run_id,
                EventType.EVIDENCE_ADDED,
                {
                    "evidence_id": eid,
                    "invoice_number": inv.invoice_number,
                    "kind": "screenshot",
                },
            )
        self.store.append(
            run_id,
            EventType.OBSERVATION,
            {
                "ok": loop_res.ok,
                "url": loop_res.data.get("url"),
                "banner": loop_res.data.get("banner"),
                "recovered_from_label": loop_res.recovered_from_label,
                "evidence": evidence_ids,
                "loop": "a11y",
                "actions": len(loop_res.actions),
            },
        )
        contra = detect_from_browser_observation(
            url=str(loop_res.data.get("url") or ""),
            banner=str(loop_res.data.get("banner") or ""),
            recovered_from_label=loop_res.recovered_from_label,
            ok=loop_res.ok,
            invoice_number=inv.invoice_number,
        )
        if contra is not None:
            self._emit_plan_revision(run_id, contra)
        if loop_res.ok:
            ledger.commit(
                key,
                result={
                    "invoice_number": inv.invoice_number,
                    "url": loop_res.data.get("url"),
                    "loop": "a11y",
                },
                step_id=f"{inv.invoice_number}:submit",
            )
        elif loop_res.failure is not None:
            self.store.append(
                run_id,
                EventType.FAILURE_CLASSIFIED,
                loop_res.failure.model_dump(mode="json"),
            )
        return InvoiceOutcome.NEEDS_ATTENTION

    def _browser_submit_shortcut(
        self,
        run_id: str,
        inv: InvoiceRecord,
        ledger: IrreversibleLedger,
        key: str,
        fields: dict[str, Any],
    ) -> InvoiceOutcome:
        """FakeLLM/CI fast path: high-level submit_invoice (still real Playwright writes)."""
        browser = self.registry.get("browser")

        def do_submit() -> Any:
            return browser.run({"action": "submit_invoice", **fields})

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
        data = res.data or {}
        obs_h = f"{data.get('url') or ''}|{data.get('banner') or ''}"
        if self.stall.observe(f"submit:{inv.invoice_number}", obs_h):
            self.store.append(
                run_id,
                EventType.STALL_DETECTED,
                {"invoice_number": inv.invoice_number, "idempotency_key": key},
            )
        if (res.data or {}).get("recovered_from_label"):
            self.store.append(
                run_id,
                EventType.RECOVERY_ATTEMPTED,
                {
                    "kind": "UI_CHANGED",
                    "detail": "label miss → stable #submit-invoice-button",
                    "idempotency_key": key,
                },
            )
            result_recoveries = getattr(self, "_recovery_count", 0) + 1
            self._recovery_count = result_recoveries
        if not res.ok:
            if res.failure is None:
                res = res.model_copy(
                    update={
                        "failure": Failure(
                            kind=FailureKind.TRANSIENT,
                            message=str((res.data or {}).get("banner") or "submit failed"),
                            retryable=True,
                        )
                    }
                )
            if res.failure.kind == FailureKind.AUTH_EXPIRED:
                self._emit_plan_revision(
                    run_id,
                    Contradiction(
                        kind=AUTH_EXPIRED,
                        reason=(
                            "Landed on login after a portal action; session assumption invalidated."
                        ),
                        invoice_number=inv.invoice_number,
                        evidence={"url": (res.data or {}).get("url")},
                    ),
                )
            self.store.append(
                run_id,
                EventType.RECOVERY_ATTEMPTED,
                {"kind": res.failure.kind.value, "idempotency_key": key},
            )
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

        evidence_ids = list((res.data or {}).get("evidence") or [])
        inv.evidence_ids = evidence_ids
        for eid in evidence_ids:
            self.store.append(
                run_id,
                EventType.EVIDENCE_ADDED,
                {
                    "evidence_id": eid,
                    "invoice_number": inv.invoice_number,
                    "kind": "screenshot",
                },
            )
        recovered_label = bool((res.data or {}).get("recovered_from_label"))
        self.store.append(
            run_id,
            EventType.OBSERVATION,
            {
                "ok": res.ok,
                "url": (res.data or {}).get("url"),
                "banner": (res.data or {}).get("banner"),
                "recovered_from_label": recovered_label,
                "evidence": evidence_ids,
                "loop": "shortcut",
            },
        )
        contra = detect_from_browser_observation(
            url=str((res.data or {}).get("url") or ""),
            banner=str((res.data or {}).get("banner") or ""),
            recovered_from_label=recovered_label,
            ok=res.ok,
            invoice_number=inv.invoice_number,
        )
        if contra is not None:
            self._emit_plan_revision(run_id, contra)
        if res.ok:
            ledger.commit(
                key,
                result={
                    "invoice_number": inv.invoice_number,
                    "url": (res.data or {}).get("url"),
                },
                step_id=f"{inv.invoice_number}:submit",
            )
            return InvoiceOutcome.NEEDS_ATTENTION
        return InvoiceOutcome.NEEDS_ATTENTION

    def _emit_plan_revision(
        self,
        run_id: str,
        contradiction: Contradiction,
        *,
        base_plan: Plan | None = None,
    ) -> None:
        """Emit real PLAN_REVISED with reason + next_steps when observations contradict."""
        plan = base_plan or self._plan
        if plan is None:
            plan = Plan(id="runtime-adapt", steps=[])
        proposal = propose_revision(plan, contradiction)
        revised = apply_revision(plan, proposal)
        if base_plan is None:
            self._plan = revised
        self.store.append(
            run_id,
            EventType.PLAN_REVISED,
            revision_event_payload(revised, proposal),
        )
        # Consume revised step args (prefer_stable_ids, relogin, wrong-page) into runtime.
        self._apply_plan_browser_prefs(revised)

    def _apply_plan_browser_prefs(self, plan: Plan) -> None:
        """Wire PLAN_REVISED args into browser setup for subsequent submits."""
        prefs = browser_prefs_from_plan(plan)
        if not prefs:
            return
        self._plan_browser_prefs.update(prefs)
        if self._browser is not None and "prefer_label_first" in prefs:
            self._browser.prefer_label_first = bool(prefs["prefer_label_first"])

    def _effective_prefer_label_first(self) -> bool:
        """Plan revision prefer_stable_ids wins over lesson/tool default."""
        if "prefer_label_first" in self._plan_browser_prefs:
            return bool(self._plan_browser_prefs["prefer_label_first"])
        if self._plan is not None:
            prefs = browser_prefs_from_plan(self._plan)
            if "prefer_label_first" in prefs:
                self._plan_browser_prefs.update(prefs)
                return bool(prefs["prefer_label_first"])
        return bool(getattr(self._browser, "prefer_label_first", False))

    def _apply_approval(self, run_id: str, approval_id: str, decision: str) -> None:
        info = self.store.decide_approval(approval_id, decision, decided_by="eval-auto")
        self.store.append(
            run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": approval_id, "decision": decision, "info": info},
        )

    def _repair_missing_submits(
        self, run_id: str, invoices: list[InvoiceRecord], ledger: IrreversibleLedger
    ) -> None:
        # Optional RPA heal after verifier miss. Off by default / on make eval so the
        # a11y measured path cannot silent-heal. make eval-rpa may enable this.
        if not self.config.allow_rpa_repair:
            self.store.append(
                run_id,
                EventType.RECOVERY_ATTEMPTED,
                {
                    "kind": "TRANSIENT",
                    "detail": "rpa repair skipped (allow_rpa_repair=False)",
                },
            )
            return
        prev = self.config.use_browser_loop
        self.config.use_browser_loop = False
        try:
            for inv in invoices:
                if inv.outcome in {
                    InvoiceOutcome.REFUSED,
                    InvoiceOutcome.FLAGGED,
                }:
                    continue
                if inv.decision not in {InvoiceDecision.SUBMIT, InvoiceDecision.NEEDS_APPROVAL}:
                    continue
                api = self.registry.get("portal_api")
                found = api.run(
                    {"action": "invoice_by_number", "invoice_number": inv.invoice_number}
                )
                if found.ok and found.data.get("result"):
                    continue
                self.store.append(
                    run_id,
                    EventType.RECOVERY_ATTEMPTED,
                    {
                        "kind": "TRANSIENT",
                        "detail": "repair via submit_invoice shortcut after a11y miss",
                        "invoice_number": inv.invoice_number,
                    },
                )
                self._browser_submit(run_id, inv, ledger)
        finally:
            self.config.use_browser_loop = prev

    def _build_report(
        self,
        run_id: str,
        invoices: list[InvoiceRecord],
        verification: VerificationResult,
        *,
        partial: bool = False,
        partial_reason: str = "",
    ) -> RunReport:
        lines: list[InvoiceLineResult] = []
        needs: list[str] = []
        security: list[str] = []
        evidence = collect_run_evidence(
            self.config.data_dir / "evidence" / run_id,
            self.config.data_dir / "verify-evidence" / run_id,
        )
        for inv in invoices:
            outcome = inv.outcome or InvoiceOutcome.NEEDS_ATTENTION
            # Operator may only report "completed" when the independent verifier passes (SPEC §7).
            if outcome == InvoiceOutcome.COMPLETED and not verification.passed:
                outcome = InvoiceOutcome.NEEDS_ATTENTION
                inv.outcome = outcome
            if partial and outcome == InvoiceOutcome.COMPLETED:
                outcome = InvoiceOutcome.NEEDS_ATTENTION
                inv.outcome = outcome
            verified = outcome == InvoiceOutcome.COMPLETED and verification.passed and not partial
            if outcome in {InvoiceOutcome.NEEDS_ATTENTION, InvoiceOutcome.FLAGGED}:
                needs.append(inv.invoice_number)
            if inv.security_finding:
                security.append(inv.invoice_number)
            citations = list(inv.policy_citations) or [
                PolicyCitation(file="invoice_processing_sop.md", section="Outcomes")
            ]
            lines.append(
                InvoiceLineResult(
                    invoice_number=inv.invoice_number,
                    outcome=outcome,
                    reason=inv.decision_reason,
                    policy_cited=citations,
                    evidence_ids=list(inv.evidence_ids),
                    verified=verified,
                )
            )
        summary = (
            f"Processed {len(invoices)} invoices. "
            f"Verified={'yes' if verification.passed and not partial else 'no'} "
            f"({verification.overall_notes})."
        )
        if partial:
            summary = f"Partial report ({partial_reason}). " + summary
        return RunReport(
            run_id=run_id,
            summary=summary,
            invoices=lines,
            verification=verification,
            needs_attention=needs,
            security_findings=security,
            evidence=evidence,
            partial=partial,
            partial_reason=partial_reason,
        )


def build_default_fake_llm() -> FakeLLM:
    """Scripts sufficient for CI understand/plan/browser_step/invoice_extract without Anthropic."""
    from ark_operator.runtime.browser_loop import scripted_browser_step
    from ark_operator.tools.pdf_extract import scripted_invoice_extract

    llm = FakeLLM(
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
                    ),
                    Step(
                        id="retrieve-knowledge",
                        description="Retrieve policies",
                        tool="knowledge_search",
                        status=StepStatus.PENDING,
                        risk_level=RiskLevel.READ,
                        depends_on=["load-invoices"],
                    ),
                    Step(
                        id="process-invoices",
                        description="Process each invoice",
                        tool="browser",
                        status=StepStatus.PENDING,
                        risk_level=RiskLevel.IRREVERSIBLE,
                        depends_on=["retrieve-knowledge"],
                    ),
                    Step(
                        id="verify",
                        description="Independent verification",
                        tool="verifier",
                        status=StepStatus.PENDING,
                        risk_level=RiskLevel.READ,
                        depends_on=["process-invoices"],
                    ),
                ],
            ),
            "browser_step": scripted_browser_step,
            "invoice_extract": scripted_invoice_extract,
        }
    )
    return llm


def build_llm(*, require_anthropic: bool = False) -> LLMClient:
    """Prefer Anthropic when ANTHROPIC_API_KEY is set; otherwise FakeLLM (CI).

    Defaults to Claude Haiku (`OPERATOR_MODEL` / `DEFAULT_OPERATOR_MODEL`).
    Never hardcodes Opus/Sonnet. Raises clearly if a real LLM is required but
    the key is missing.
    """
    from ark_operator.config import get_settings

    settings = get_settings()
    if settings.anthropic_api_key:
        from ark_operator.llm.anthropic_client import AnthropicClient

        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.operator_model,
        )
    if require_anthropic:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required (set in environment or `.env`; "
            "see `.env.example`). OPERATOR_MODEL defaults to claude-haiku-5-5."
        )
    return build_default_fake_llm()
