"""One-action-at-a-time browser execute→observe→adapt loop (SPEC §6.5–6.7)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ark_operator.domain.enums import FailureKind
from ark_operator.domain.models import BrowserActionChoice, Failure
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.base import LLMClient
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.recovery import Recovery
from ark_operator.runtime.stall_detector import StallDetector
from ark_operator.tools.base import ToolResult
from ark_operator.tools.browser import BrowserTool


@dataclass
class BrowserLoopResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    failure: Failure | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    recovered_from_label: bool = False


@dataclass
class BrowserLoop:
    """Observe a11y tree → LLM picks one action → tool → repeat until done/budgets/stall."""

    llm: LLMClient
    browser: BrowserTool
    store: EventStore
    run_id: str
    stall: StallDetector
    recovery: Recovery
    budgets: Budgets
    max_actions: int = 30
    prefer_label_first: bool = False

    def run_submit(
        self, fields: dict[str, Any], *, step_id: str, idempotency_key: str
    ) -> BrowserLoopResult:
        """Drive portal submit via low-level a11y actions until postcondition or stop."""
        goal = (
            f"Submit invoice {fields.get('invoice_number')} for vendor "
            f"{fields.get('vendor')} against PO {fields.get('po_number')} "
            f"amount {fields.get('amount')} into AcmeCorp Procure."
        )
        history: list[dict[str, Any]] = []
        evidence: list[str] = []
        recovered_from_label = False
        last_obs: dict[str, Any] = {}

        def _fail_data() -> dict[str, Any]:
            return {
                "observation": last_obs,
                "evidence": evidence,
                "url": last_obs.get("url"),
            }

        for _ in range(self.max_actions):
            self.budgets.record_step()
            budget = self.budgets.check()
            if budget == "warning":
                self.budgets.mark_warned()
                self.store.append(
                    self.run_id,
                    EventType.BUDGET_WARNING,
                    {"scope": "browser_loop", "ratios": self.budgets.ratios()},
                    step_id=step_id,
                )
            if budget == "exhausted":
                return BrowserLoopResult(
                    ok=False,
                    data=_fail_data(),
                    failure=Failure(
                        kind=FailureKind.UNRECOVERABLE,
                        message="browser_loop_budget_exhausted",
                    ),
                    actions=history,
                    recovered_from_label=recovered_from_label,
                )

            obs_res = self.browser.run({"action": "observe"})
            if not obs_res.ok:
                return BrowserLoopResult(
                    ok=False,
                    data={"evidence": evidence},
                    failure=obs_res.failure,
                    actions=history,
                    recovered_from_label=recovered_from_label,
                )
            last_obs = dict(obs_res.data or {})
            compact = _compact_observation(last_obs)
            self.store.append(
                self.run_id,
                EventType.OBSERVATION,
                {"kind": "a11y", "url": last_obs.get("url"), "summary": compact[:800]},
                step_id=step_id,
            )

            if _postcondition_met(last_obs):
                return BrowserLoopResult(
                    ok=True,
                    data={
                        "observation": last_obs,
                        "evidence": evidence,
                        "url": last_obs.get("url"),
                        "banner": " ".join(last_obs.get("banners") or []),
                        "recovered_from_label": recovered_from_label,
                        "loop": "a11y",
                    },
                    actions=history,
                    recovered_from_label=recovered_from_label,
                )

            choice = self._choose(goal, fields, compact, history)
            action_payload = choice.model_dump(mode="json")
            history.append(action_payload)
            action_h = f"{choice.action}:{choice.ref or choice.url or ''}"
            obs_h = str(hash(compact))
            if self.stall.observe(action_h, obs_h):
                self.store.append(
                    self.run_id,
                    EventType.STALL_DETECTED,
                    {"step_id": step_id, "action": action_payload},
                    step_id=step_id,
                )
                return BrowserLoopResult(
                    ok=False,
                    data=_fail_data(),
                    failure=Failure(
                        kind=FailureKind.UNRECOVERABLE,
                        message="browser_loop_stall",
                    ),
                    actions=history,
                    recovered_from_label=recovered_from_label,
                )

            if choice.action == "done":
                # LLM claims done — re-check postcondition once more.
                if _postcondition_met(last_obs):
                    return BrowserLoopResult(
                        ok=True,
                        data={
                            "observation": last_obs,
                            "evidence": evidence,
                            "url": last_obs.get("url"),
                            "banner": " ".join(last_obs.get("banners") or []),
                            "recovered_from_label": recovered_from_label,
                            "loop": "a11y",
                        },
                        actions=history,
                        recovered_from_label=recovered_from_label,
                    )
                continue
            if choice.action == "abort":
                return BrowserLoopResult(
                    ok=False,
                    data={"observation": last_obs, "evidence": evidence},
                    failure=Failure(
                        kind=FailureKind.UNRECOVERABLE,
                        message=choice.rationale or "browser_loop_abort",
                    ),
                    actions=history,
                    recovered_from_label=recovered_from_label,
                )

            tool_args = _choice_to_tool_args(choice)
            bound_args = dict(tool_args)
            self.store.append(
                self.run_id,
                EventType.TOOL_CALL,
                {
                    "tool": "browser",
                    "action": choice.action,
                    "args": {k: v for k, v in bound_args.items() if k != "action"},
                    "rationale": choice.rationale,
                    "idempotency_key": idempotency_key,
                    "loop": "a11y",
                },
                step_id=step_id,
            )

            def call(args: dict[str, Any] = bound_args) -> ToolResult:
                return self.browser.run(args)

            result = call()
            if (
                not result.ok
                and result.failure is not None
                and result.failure.kind == FailureKind.ELEMENT_NOT_FOUND
                and choice.action == "click"
                and self.prefer_label_first
            ):
                # Learning lever: label miss → re-resolve stable submit id (SPEC §6.6).
                fallback = self._click_stable_submit()
                if fallback.ok:
                    recovered_from_label = True
                    self.store.append(
                        self.run_id,
                        EventType.RECOVERY_ATTEMPTED,
                        {
                            "kind": "UI_CHANGED",
                            "detail": "label miss → stable #submit-invoice-button",
                            "idempotency_key": idempotency_key,
                        },
                        step_id=step_id,
                    )
                    result = fallback
                else:
                    fail = result.failure
                    assert fail is not None
                    handled = self.recovery.handle(
                        f"{idempotency_key}:{choice.action}",
                        fail,
                        retry=call,
                        relogin=lambda: self.browser.run({"action": "login"}),
                    )
                    if isinstance(handled, ToolResult):
                        result = handled
                    else:
                        history[-1]["error"] = handled.message
                        continue
            elif not result.ok and result.failure is not None:
                fail = result.failure
                if fail.kind == FailureKind.AUTH_EXPIRED:
                    self.store.append(
                        self.run_id,
                        EventType.RECOVERY_ATTEMPTED,
                        {"kind": "AUTH_EXPIRED", "idempotency_key": idempotency_key},
                        step_id=step_id,
                    )
                handled = self.recovery.handle(
                    f"{idempotency_key}:{choice.action}",
                    fail,
                    retry=call,
                    relogin=lambda: self.browser.run({"action": "login"}),
                )
                if isinstance(handled, ToolResult):
                    result = handled
                else:
                    history[-1]["error"] = handled.message
                    if not handled.retryable and handled.kind in {
                        FailureKind.POLICY_BLOCK,
                        FailureKind.UNRECOVERABLE,
                        FailureKind.DATA_CONFLICT,
                    }:
                        return BrowserLoopResult(
                            ok=False,
                            data={"observation": last_obs, "evidence": evidence},
                            failure=handled,
                            actions=history,
                            recovered_from_label=recovered_from_label,
                        )
                    continue

            ev = list((result.data or {}).get("evidence") or [])
            evidence.extend(str(x) for x in ev)
            if result.observation and result.observation.data:
                last_obs = dict(result.observation.data)
            elif isinstance(result.data, dict) and "observation" in result.data:
                last_obs = dict(result.data["observation"] or {})
            elif isinstance(result.data, dict) and "url" in (result.data or {}):
                last_obs = dict(result.data)

        return BrowserLoopResult(
            ok=False,
            data={"observation": last_obs, "evidence": evidence, "url": last_obs.get("url")},
            failure=Failure(kind=FailureKind.UNRECOVERABLE, message="browser_loop_max_actions"),
            actions=history,
            recovered_from_label=recovered_from_label,
        )

    def _choose(
        self,
        goal: str,
        fields: dict[str, Any],
        observation: str,
        history: list[dict[str, Any]],
    ) -> BrowserActionChoice:
        hints = []
        if self.prefer_label_first:
            hints.append(
                "Prefer clicking the button whose visible name is exactly 'Submit invoice' "
                "before using id=submit-invoice-button."
            )
        else:
            hints.append(
                "Prefer stable element ids (id=submit-invoice-button, id=vendor_id, …) "
                "over visible labels when clicking/filling."
            )
        hints.append("Use action login (not fill password) when on /login or session expired.")
        variables = {
            "goal": goal,
            "fields": json.dumps(fields, sort_keys=True),
            "hints": "\n".join(f"- {h}" for h in hints),
            "history": json.dumps(history[-12:], sort_keys=True),
            "observation": observation,
        }
        resp = self.llm.complete("browser_step", variables, schema=BrowserActionChoice)
        self.budgets.record_llm(resp.tokens_in + resp.tokens_out, resp.cost_usd)
        content = resp.content
        if isinstance(content, BrowserActionChoice):
            return content
        if isinstance(content, dict):
            return BrowserActionChoice.model_validate(content)
        raise TypeError(f"Unexpected browser_step content: {type(content)}")

    def _click_stable_submit(self) -> ToolResult:
        obs = self.browser.run({"action": "observe"})
        if not obs.ok:
            return obs
        ref = _ref_for_id(obs.data or {}, "submit-invoice-button")
        if not ref:
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.ELEMENT_NOT_FOUND,
                    message="stable submit button ref missing",
                    retryable=True,
                ),
            )
        return self.browser.run({"action": "click", "ref": ref})


def _compact_observation(obs: dict[str, Any]) -> str:
    lines = [
        f"title: {obs.get('title', '')}",
        f"url: {obs.get('url', '')}",
    ]
    banners = obs.get("banners") or []
    if banners:
        lines.append("banners: " + " | ".join(str(b) for b in banners))
    for el in obs.get("elements") or []:
        lines.append(str(el))
    return "\n".join(lines)


def _postcondition_met(obs: dict[str, Any]) -> bool:
    url = str(obs.get("url") or "")
    banners = " ".join(obs.get("banners") or [])
    landed = "/invoices/" in url and "/submit" not in url and "/login" not in url
    return landed and "Duplicate submit blocked" not in banners


def _ref_for_id(obs: dict[str, Any], element_id: str) -> str | None:
    for line in obs.get("elements") or []:
        if f"id={element_id}" in str(line):
            match = re.search(r"\[(e\d+)\]", str(line))
            if match:
                return match.group(1)
    return None


def _choice_to_tool_args(choice: BrowserActionChoice) -> dict[str, Any]:
    args: dict[str, Any] = {"action": choice.action}
    if choice.ref:
        args["ref"] = choice.ref
    if choice.text is not None and choice.action in {"fill", "wait_for"}:
        args["text"] = choice.text
    if choice.value is not None:
        args["value"] = choice.value
    if choice.url:
        args["url"] = choice.url
    if choice.key:
        args["key"] = choice.key
    if choice.action == "wait_for" and choice.text:
        args["text"] = choice.text
    return args


def scripted_browser_step(variables: dict[str, Any]) -> dict[str, Any]:
    """Deterministic FakeLLM driver for the a11y loop (CI / integration tests)."""
    obs = str(variables.get("observation") or "")
    history_raw = variables.get("history") or "[]"
    try:
        history = json.loads(history_raw) if isinstance(history_raw, str) else list(history_raw)
    except json.JSONDecodeError:
        history = []
    fields_raw = variables.get("fields") or "{}"
    try:
        fields = json.loads(fields_raw) if isinstance(fields_raw, str) else dict(fields_raw)
    except json.JSONDecodeError:
        fields = {}
    hints = str(variables.get("hints") or "")
    prefer_label = "exactly 'Submit invoice'" in hints or 'exactly "Submit invoice"' in hints

    def find_ref(element_id: str) -> str | None:
        for line in obs.splitlines():
            if f"id={element_id}" in line:
                match = re.search(r"\[(e\d+)\]", line)
                if match:
                    return match.group(1)
        return None

    def line_for_id(element_id: str) -> str:
        for line in obs.splitlines():
            if f"id={element_id}" in line:
                return line
        return ""

    def field_done(eid: str, expected: str) -> bool:
        """True when observation shows an input already holds the expected value."""
        line = line_for_id(eid)
        if not line or not expected:
            return False
        return f"value='{expected}'" in line or f'value="{expected}"' in line

    def already_set(eid: str) -> bool:
        return any(
            isinstance(h, dict)
            and h.get("action") in {"fill", "select"}
            and eid in str(h.get("rationale") or "")
            and not h.get("error")
            for h in history
        )

    url_line = next((ln for ln in obs.splitlines() if ln.startswith("url:")), "")
    url = url_line.split("url:", 1)[-1].strip()

    if _script_postcondition(url, obs):
        return {"action": "done", "rationale": "postcondition met"}

    if "/login" in url or ("id=login-submit" in obs and "/dashboard" not in url):
        return {"action": "login", "rationale": "establish session"}

    if "/invoices/submit" not in url:
        if "id=email" in obs and "id=password" in obs:
            return {"action": "login", "rationale": "login form visible"}
        return {"action": "goto", "url": "/invoices/submit", "rationale": "open submit form"}

    amount_text = f"{float(fields.get('amount') or 0):.2f}"
    plan: list[tuple[str, str, str, str]] = [
        ("select", "vendor_id", "value", str(fields.get("vendor") or "")),
        ("fill", "invoice_number", "text", str(fields.get("invoice_number") or "")),
        ("select", "po_id", "value", str(fields.get("po_number") or "")),
        ("fill", "amount", "text", amount_text),
        ("fill", "invoice_date", "text", str(fields.get("invoice_date") or "")),
        ("fill", "attachment_name", "text", str(fields.get("attachment_name") or "")),
    ]
    for action, eid, arg_key, arg_val in plan:
        if not arg_val:
            continue
        if field_done(eid, arg_val) or already_set(eid):
            continue
        ref = find_ref(eid)
        if ref is None:
            continue
        payload: dict[str, Any] = {
            "action": action,
            "ref": ref,
            "rationale": f"set {eid}",
        }
        payload[arg_key] = arg_val
        return payload

    tried_label = any(
        isinstance(h, dict) and "prefer label" in str(h.get("rationale") or "") for h in history
    )
    if prefer_label and not tried_label:
        # Prefer exact visible name on a button (not nav <a>); under ui_rename this misses.
        label_ref = None
        for line in obs.splitlines():
            if "button" in line.lower() and "submit invoice" in line.lower():
                match = re.search(r"\[(e\d+)\]", line)
                if match:
                    label_ref = match.group(1)
                    break
        if label_ref:
            return {
                "action": "click",
                "ref": label_ref,
                "rationale": "prefer label Submit invoice",
            }
        return {
            "action": "click",
            "ref": "e_missing_submit_label",
            "rationale": "prefer label Submit invoice",
        }

    submit_ref = find_ref("submit-invoice-button")
    if submit_ref:
        return {
            "action": "click",
            "ref": submit_ref,
            "rationale": "stable id submit-invoice-button",
        }
    return {"action": "abort", "rationale": "submit control not found"}


def _script_postcondition(url: str, obs: str) -> bool:
    return (
        "/invoices/" in url
        and "/submit" not in url
        and "/login" not in url
        and "Duplicate submit blocked" not in obs
    )
