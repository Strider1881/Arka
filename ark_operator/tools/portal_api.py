"""Read-only portal helpers for the verifier and cheap lookups (SPEC §6.8)."""

from __future__ import annotations

from typing import Any

import httpx

from ark_operator.domain.enums import FailureKind, RiskLevel
from ark_operator.domain.models import Failure, Observation
from ark_operator.tools.base import BaseTool, ToolResult


class PortalApiTool(BaseTool):
    """Read-only AcmeCorp Procure API client. Never used for writes by the executor."""

    name = "portal_api"
    risk_class = RiskLevel.READ
    timeout_seconds = 15.0
    description = "Read-only portal lookups (verifier / cheap reads only)"

    def __init__(
        self,
        base_url: str,
        *,
        email: str,
        password: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self._client = httpx.Client(base_url=self.base_url, follow_redirects=False, timeout=15.0)
        self._authed = False

    def close(self) -> None:
        self._client.close()

    def _login(self) -> None:
        if self._authed:
            return
        r = self._client.post(
            "/login",
            data={"email": self.email, "password": self.password},
        )
        if r.status_code not in (200, 303, 302):
            raise RuntimeError(f"Portal login failed: {r.status_code}")
        self._authed = True

    def _run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "invoices"))
        try:
            self._login()
            if action == "vendors":
                data = self._client.get("/api/vendors").json()
            elif action == "pos":
                data = self._client.get("/api/pos").json()
            elif action == "invoices":
                data = self._client.get("/api/invoices").json()
            elif action == "invoice_by_number":
                number = str(args["invoice_number"])
                all_inv = self._client.get("/api/invoices").json()
                data = next((i for i in all_inv if i.get("invoice_number") == number), None)
            else:
                return ToolResult(
                    ok=False,
                    failure=Failure(
                        kind=FailureKind.VALIDATION, message=f"Unknown action {action}"
                    ),
                )
            return ToolResult(
                ok=True,
                observation=Observation(summary=f"portal_api {action}", data={"result": data}),
                data={"result": data},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                failure=Failure(kind=FailureKind.TRANSIENT, message=str(exc), retryable=True),
            )
