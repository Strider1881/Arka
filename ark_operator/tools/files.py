"""List/read files within an allowlisted sandbox root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ark_operator.domain.enums import FailureKind, RiskLevel
from ark_operator.domain.models import Failure, Observation
from ark_operator.tools.base import BaseTool, ToolResult


class FilesTool(BaseTool):
    """Sandboxed filesystem access."""

    name = "files"
    risk_class = RiskLevel.READ
    timeout_seconds = 10.0
    description = "List or read files under an allowlisted root"

    def __init__(self, sandbox_roots: list[Path] | None = None) -> None:
        roots = sandbox_roots or [Path("company_world")]
        self.sandbox_roots = [r.resolve() for r in roots]

    def _resolve(self, path: str) -> Path:
        candidate = Path(path).resolve()
        for root in self.sandbox_roots:
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                continue
        raise PermissionError(f"Path outside sandbox: {path}")

    def _run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "list"))
        path = str(args.get("path", "company_world/inbox"))
        try:
            target = self._resolve(path)
        except PermissionError as exc:
            return ToolResult(
                ok=False,
                failure=Failure(kind=FailureKind.POLICY_BLOCK, message=str(exc)),
            )
        if action == "list":
            if not target.exists():
                return ToolResult(
                    ok=False,
                    failure=Failure(kind=FailureKind.UNRECOVERABLE, message=f"Missing {target}"),
                )
            entries = sorted(p.name for p in target.iterdir())
            return ToolResult(
                ok=True,
                observation=Observation(
                    summary=f"Listed {len(entries)} entries", data={"entries": entries}
                ),
                data={"entries": entries, "path": str(target)},
            )
        if action == "read":
            text = target.read_text(encoding="utf-8", errors="replace")
            return ToolResult(
                ok=True,
                observation=Observation(summary=f"Read {target.name}", data={"chars": len(text)}),
                data={"text": text, "path": str(target)},
            )
        return ToolResult(
            ok=False,
            failure=Failure(kind=FailureKind.VALIDATION, message=f"Unknown action {action}"),
        )
