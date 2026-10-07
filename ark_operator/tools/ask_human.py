"""Create Approval/Question records and pause the run durably."""

from __future__ import annotations

import uuid
from typing import Any

from ark_operator.domain.enums import RiskLevel
from ark_operator.domain.models import Observation
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.tools.base import BaseTool, ToolResult


class AskHumanTool(BaseTool):
    """Ask the human when genuinely blocked."""

    name = "ask_human"
    risk_class = RiskLevel.READ
    timeout_seconds = 5.0
    description = "Create a durable approval/question and pause the run"

    def __init__(self, store: EventStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    def _run(self, args: dict[str, Any]) -> ToolResult:
        prompt = str(args.get("prompt") or args.get("question") or "Need human input")
        options = args.get("options") or ["provide_po", "reject", "approve_exception"]
        if not isinstance(options, list):
            options = ["approve", "reject"]
        approval_id = str(args.get("approval_id") or uuid.uuid4())
        step_id = str(args.get("step_id") or "")
        context = {k: v for k, v in args.items() if k not in {"prompt", "question", "options"}}
        self.store.save_approval(
            approval_id,
            self.run_id,
            prompt,
            step_id=step_id,
            options=[str(o) for o in options],
            context=context,
        )
        self.store.append(
            self.run_id,
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": approval_id,
                "prompt": prompt,
                "options": options,
                "context": context,
            },
            step_id=step_id or None,
        )
        return ToolResult(
            ok=True,
            observation=Observation(
                summary="Awaiting human decision",
                data={"approval_id": approval_id, "status": "PENDING"},
            ),
            data={"approval_id": approval_id, "status": "PENDING", "paused": True},
        )
