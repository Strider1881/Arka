"""Execute-observe-adapt loop for plan steps (SPEC §6.5)."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.enums import PolicyDecision, RiskLevel
from ark_operator.domain.models import Step
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.base import LLMClient
from ark_operator.policy.engine import PolicyEngine
from ark_operator.runtime.browser_loop import BrowserLoop, BrowserLoopResult
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.recovery import Recovery
from ark_operator.runtime.stall_detector import StallDetector
from ark_operator.tools.base import ToolResult
from ark_operator.tools.browser import BrowserTool
from ark_operator.tools.registry import ToolRegistry


class Executor:
    """Runs ready steps via tools with policy and budgets.

    Portal invoice writes can also run as a one-action-at-a-time a11y loop
    via :meth:`run_browser_submit` (SPEC §6.5–6.7).
    """

    def __init__(
        self,
        store: EventStore,
        registry: ToolRegistry,
        policy: PolicyEngine,
        recovery: Recovery,
        stall: StallDetector,
        run_id: str,
        *,
        llm: LLMClient | None = None,
        budgets: Budgets | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.policy = policy
        self.recovery = recovery
        self.stall = stall
        self.run_id = run_id
        self.llm = llm
        self.budgets = budgets or Budgets()

    def run_browser_submit(
        self,
        fields: dict[str, Any],
        *,
        step_id: str,
        idempotency_key: str,
        prefer_label_first: bool = False,
        max_actions: int = 30,
        relogin_on_auth_expired: bool = True,
        recover_wrong_page: bool = True,
        recover_goto: str = "/invoices/submit",
    ) -> BrowserLoopResult:
        """LLM chooses one a11y action at a time until invoice submit postcondition."""
        if self.llm is None:
            raise RuntimeError("Executor.run_browser_submit requires an LLMClient")
        browser = self.registry.get("browser")
        if not isinstance(browser, BrowserTool):
            raise TypeError("browser tool must be BrowserTool for a11y loop")
        loop = BrowserLoop(
            llm=self.llm,
            browser=browser,
            store=self.store,
            run_id=self.run_id,
            stall=self.stall,
            recovery=self.recovery,
            budgets=self.budgets,
            max_actions=max_actions,
            prefer_label_first=prefer_label_first,
            relogin_on_auth_expired=relogin_on_auth_expired,
            recover_wrong_page=recover_wrong_page,
            recover_goto=recover_goto,
        )
        return loop.run_submit(fields, step_id=step_id, idempotency_key=idempotency_key)

    def run_step(self, step: Step) -> ToolResult:
        """Execute one step with policy check, tool call, observation."""
        decision, rule = self.policy.decide_tool(step.tool, step.risk_level)
        if decision == PolicyDecision.DENY:
            self.store.append(
                self.run_id,
                EventType.FAILURE_CLASSIFIED,
                {"kind": "POLICY_BLOCK", "rule": rule},
                step_id=step.id,
            )
            from ark_operator.domain.enums import FailureKind
            from ark_operator.domain.models import Failure

            return ToolResult(
                ok=False,
                failure=Failure(kind=FailureKind.POLICY_BLOCK, message=rule),
            )
        if (
            decision == PolicyDecision.REQUIRE_APPROVAL
            and step.risk_level == RiskLevel.IRREVERSIBLE
        ):
            # Caller should pause; we still refuse silent irreversible without clearance flag
            if not step.args.get("cleared"):
                from ark_operator.domain.enums import FailureKind
                from ark_operator.domain.models import Failure

                return ToolResult(
                    ok=False,
                    failure=Failure(
                        kind=FailureKind.POLICY_BLOCK,
                        message="irreversible_without_clearance",
                    ),
                )

        key = step.idempotency_key or step.id
        cached = self.store.get_idempotent(key)
        if cached is not None:
            self.store.append(
                self.run_id,
                EventType.IDEMPOTENCY_SKIP,
                {"idempotency_key": key},
                step_id=step.id,
            )
            return ToolResult(ok=True, data=cached)

        self.store.append(
            self.run_id,
            EventType.STEP_STARTED,
            {"tool": step.tool, "args": _redact(step.args)},
            step_id=step.id,
        )
        tool = self.registry.get(step.tool)

        def call() -> ToolResult:
            self.store.append(
                self.run_id,
                EventType.TOOL_CALL,
                {"tool": step.tool, "args": _redact(step.args)},
                step_id=step.id,
            )
            return tool.run(step.args)

        result = call()
        if not result.ok and result.failure is not None:
            handled = self.recovery.handle(key, result.failure, retry=call)
            if isinstance(handled, ToolResult):
                result = handled
            else:
                self.store.append(
                    self.run_id,
                    EventType.STEP_FAILED,
                    handled.model_dump(mode="json"),
                    step_id=step.id,
                )
                return ToolResult(ok=False, failure=handled)

        obs_payload = (
            result.observation.model_dump(mode="json") if result.observation else result.data
        )
        self.store.append(self.run_id, EventType.OBSERVATION, obs_payload, step_id=step.id)
        action_h = f"{step.tool}:{sorted(step.args.keys())}"
        obs_h = str(hash(str(obs_payload)))
        if self.stall.observe(action_h, obs_h):
            self.store.append(self.run_id, EventType.STALL_DETECTED, {"step_id": step.id})
        self.store.remember_idempotent(key, self.run_id, result.data, step_id=step.id)
        self.store.append(
            self.run_id,
            EventType.STEP_COMPLETED,
            {"idempotency_key": key, "ok": result.ok},
            step_id=step.id,
        )
        return result


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    for k in list(out):
        if "password" in k.lower() or "secret" in k.lower() or "api_key" in k.lower():
            out[k] = "***REDACTED***"
    return out
