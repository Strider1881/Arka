"""Base tool protocol: name, schema, risk, timeout, typed results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from ark_operator.domain.enums import FailureKind, RiskLevel
from ark_operator.domain.models import Failure, Observation


class ToolResult(BaseModel):
    ok: bool = True
    observation: Observation | None = None
    failure: Failure | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    """Every tool declares metadata and returns ToolResult (never bare exceptions)."""

    name: str = "base"
    risk_class: RiskLevel = RiskLevel.READ
    timeout_seconds: float = 30.0
    description: str = ""

    def args_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            return self._run(args)
        except Exception as exc:  # noqa: BLE001 — tools must not leak bare exceptions
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.UNRECOVERABLE,
                    message=str(exc),
                    retryable=False,
                    details={"tool": self.name},
                ),
            )

    @abstractmethod
    def _run(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
