"""Observation-driven plan revision when the world contradicts assumptions (SPEC §6.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ark_operator.domain.enums import RiskLevel, StepStatus
from ark_operator.domain.models import Plan, Step

# Contradiction kinds that justify a real PLAN_REVISED (not cosmetic copy edits).
UI_RENAME = "UI_RENAME"
WRONG_PAGE = "WRONG_PAGE"
MISSING_PO = "MISSING_PO"
AUTH_EXPIRED = "AUTH_EXPIRED"
FIELD_MISSING = "FIELD_MISSING"


@dataclass(frozen=True)
class Contradiction:
    kind: str
    reason: str
    invoice_number: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RevisionProposal:
    reason: str
    kind: str
    next_steps: list[str]
    changes: list[dict[str, Any]]
    invoice_number: str | None = None


def detect_from_browser_observation(
    *,
    url: str | None,
    banner: str | None = None,
    recovered_from_label: bool = False,
    ok: bool | None = None,
    invoice_number: str | None = None,
    expected_path: str = "/invoices/",
) -> Contradiction | None:
    """Classify contradictions from a portal browser observation."""
    url_s = str(url or "")
    banner_s = str(banner or "")

    if recovered_from_label:
        return Contradiction(
            kind=UI_RENAME,
            reason=(
                "Visible submit label missing or renamed; recovered via stable "
                "#submit-invoice-button (role/name → id)."
            ),
            invoice_number=invoice_number,
            evidence={"url": url_s, "banner": banner_s, "recovered_from_label": True},
        )

    if "/login" in url_s:
        return Contradiction(
            kind=AUTH_EXPIRED,
            reason="Landed on login after a portal action; session assumption invalidated.",
            invoice_number=invoice_number,
            evidence={"url": url_s, "banner": banner_s},
        )

    if ok is False and "/submit" in url_s:
        return Contradiction(
            kind=WRONG_PAGE,
            reason=(
                "Still on submit form after submit attempt; expected invoice detail/list landing."
            ),
            invoice_number=invoice_number,
            evidence={"url": url_s, "banner": banner_s, "expected_path": expected_path},
        )

    if ok is False and url_s and expected_path not in url_s and "/invoices/submit" not in url_s:
        return Contradiction(
            kind=WRONG_PAGE,
            reason=f"Unexpected page after action (url={url_s}); expected path containing "
            f"{expected_path!r}.",
            invoice_number=invoice_number,
            evidence={"url": url_s, "banner": banner_s},
        )

    return None


def detect_missing_po(
    *,
    invoice_number: str,
    po_number: str | None,
    decision: str | None = None,
) -> Contradiction | None:
    """Extraction/tool observation: invoice lacks a PO when policy needs one."""
    if po_number and str(po_number).strip():
        return None
    if decision and decision not in {"flag_ask_human", "FLAG_ASK_HUMAN", ""}:
        # Policy already chose a non-ask path; no plan contradiction.
        return None
    return Contradiction(
        kind=MISSING_PO,
        reason=f"{invoice_number} has no PO number; cannot assume three-way match — ask human.",
        invoice_number=invoice_number,
        evidence={"po_number": po_number or ""},
    )


def propose_revision(plan: Plan, contradiction: Contradiction) -> RevisionProposal:
    """Turn a contradiction into concrete next steps + plan changes."""
    inv = contradiction.invoice_number or ""
    kind = contradiction.kind

    if kind == UI_RENAME:
        return RevisionProposal(
            reason=contradiction.reason,
            kind=kind,
            next_steps=[
                "Re-observe accessibility tree",
                "Re-resolve submit by role/name/label then stable id #submit-invoice-button",
                "Retry irreversible submit once with prefer_stable_ids=true",
                "Record episodic lesson for later runs",
            ],
            changes=[
                {
                    "step_id": "process-invoices",
                    "description": (
                        "Process invoices using stable element ids (label-first abandoned)"
                    ),
                    "args": {"prefer_stable_ids": True, "ui_resolve": "id_first"},
                }
            ],
            invoice_number=contradiction.invoice_number,
        )

    if kind == AUTH_EXPIRED:
        return RevisionProposal(
            reason=contradiction.reason,
            kind=kind,
            next_steps=[
                "Run login action (secrets provider; never LLM-visible password)",
                "Resume interrupted submit with same idempotency key",
            ],
            changes=[
                {
                    "step_id": "process-invoices",
                    "description": "Re-login on AUTH_EXPIRED then resume idempotent submit",
                    "args": {"relogin_on_auth_expired": True},
                }
            ],
            invoice_number=contradiction.invoice_number,
        )

    if kind == WRONG_PAGE:
        return RevisionProposal(
            reason=contradiction.reason,
            kind=kind,
            next_steps=[
                "Goto /invoices/submit",
                "Re-fill form from invoice fields",
                "Submit via stable ids",
            ],
            changes=[
                {
                    "step_id": "process-invoices",
                    "description": "Recover wrong-page: navigate to submit form and retry",
                    "args": {"recover_wrong_page": True, "goto": "/invoices/submit"},
                }
            ],
            invoice_number=contradiction.invoice_number,
        )

    if kind == MISSING_PO:
        ask_id = f"{inv}:ask" if inv else "ask-missing-po"
        return RevisionProposal(
            reason=contradiction.reason,
            kind=kind,
            next_steps=[
                f"Do not guess a PO for {inv or 'invoice'}",
                "Open AskHuman with options (provide PO / skip / escalate)",
                "Pause run until human decides",
            ],
            changes=[
                {
                    "step_id": ask_id,
                    "description": f"Ask human about missing PO for {inv}",
                    "args": {"action": "ask", "invoice_number": inv, "reason": "missing_po"},
                    "insert_if_missing": True,
                    "tool": "ask_human",
                    "risk_level": RiskLevel.READ.value,
                }
            ],
            invoice_number=contradiction.invoice_number,
        )

    # FIELD_MISSING / default
    return RevisionProposal(
        reason=contradiction.reason,
        kind=kind,
        next_steps=["Re-observe", "Re-resolve target", "Retry or escalate honestly"],
        changes=[
            {
                "step_id": "process-invoices",
                "description": f"Adapted after {kind}: {contradiction.reason[:120]}",
                "args": {"last_contradiction": kind},
            }
        ],
        invoice_number=contradiction.invoice_number,
    )


def apply_revision(plan: Plan, proposal: RevisionProposal) -> Plan:
    """Apply proposal changes: update matching steps; insert ask steps when missing."""
    revised = plan.model_copy(deep=True)
    revised.revision += 1
    existing_ids = {s.id for s in revised.steps}

    for change in proposal.changes:
        sid = str(change.get("step_id", ""))
        matched = False
        for step in revised.steps:
            if step.id != sid:
                continue
            matched = True
            if "args" in change and isinstance(change["args"], dict):
                step.args.update(change["args"])
            if "description" in change:
                step.description = str(change["description"])
        if not matched and change.get("insert_if_missing"):
            if sid in existing_ids:
                continue
            revised.steps.append(
                Step(
                    id=sid,
                    description=str(change.get("description") or sid),
                    tool=str(change.get("tool") or "ask_human"),
                    args=dict(change.get("args") or {}),
                    risk_level=RiskLevel(change.get("risk_level") or RiskLevel.READ.value),
                    status=StepStatus.READY,
                    idempotency_key=sid,
                    invoice_number=proposal.invoice_number,
                )
            )
            existing_ids.add(sid)
    return revised


def revision_event_payload(plan: Plan, proposal: RevisionProposal) -> dict[str, Any]:
    """Payload for PLAN_REVISED — reason + next_steps are first-class, not buried."""
    return {
        "plan_id": plan.id,
        "revision": plan.revision,
        "reason": proposal.reason,
        "kind": proposal.kind,
        "next_steps": proposal.next_steps,
        "invoice_number": proposal.invoice_number,
        "changes": proposal.changes,
        "steps": [s.model_dump(mode="json") for s in plan.steps],
        "browser_prefs": browser_prefs_from_plan(plan),
    }


def browser_prefs_from_plan(plan: Plan) -> dict[str, Any]:
    """Extract runtime browser prefs from revised plan step args (consumed by pipeline)."""
    prefs: dict[str, Any] = {}
    for step in plan.steps:
        args = step.args or {}
        if args.get("prefer_stable_ids") is True or args.get("ui_resolve") == "id_first":
            prefs["prefer_stable_ids"] = True
            prefs["prefer_label_first"] = False
        if args.get("relogin_on_auth_expired") is True:
            prefs["relogin_on_auth_expired"] = True
        if args.get("recover_wrong_page") is True:
            prefs["recover_wrong_page"] = True
            if args.get("goto"):
                prefs["recover_goto"] = str(args["goto"])
    return prefs
