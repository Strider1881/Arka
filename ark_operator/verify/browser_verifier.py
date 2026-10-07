"""Independent verifier using a *fresh* Playwright browser context (SPEC §7).

Never shares cookies/storage with the executor BrowserTool. Also uses a fresh
portal_api HTTP session for structured reads. The agent never grades itself.

Playwright sync API runs in a dedicated worker thread so it never collides with
pytest-asyncio / FastAPI event loops.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ark_operator.domain.enums import Confidence
from ark_operator.domain.models import CriterionResult, InvoiceRecord, VerificationResult
from ark_operator.tools.portal_api import PortalApiTool
from ark_operator.tools.secrets import portal_operator_credentials
from ark_operator.verify.checks import check_invoice_against_portal


class BrowserVerifier:
    """Ground-truth checks via isolated Chromium context + read-only portal API."""

    def __init__(
        self,
        base_url: str,
        *,
        evidence_dir: Path | None = None,
        headless: bool = True,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        creds = portal_operator_credentials()
        self.base_url = base_url.rstrip("/")
        self.evidence_dir = Path(evidence_dir) if evidence_dir else Path("data/verify-evidence")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.email = email or creds.email
        self.password = password or creds.password
        self._api = PortalApiTool(self.base_url, email=self.email, password=self.password)
        self.context_id: str | None = None
        self._last_storage: dict[str, Any] = {}

    def close(self) -> None:
        self._api.close()

    def storage_state(self) -> dict[str, Any]:
        return dict(self._last_storage)

    def _probe_isolated_browser(self) -> tuple[str, dict[str, Any], str]:
        """Create, use, and tear down a Playwright context entirely in one thread."""

        def _run() -> tuple[str, dict[str, Any], str]:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context()
            ctx_id = f"verify-{id(context)}"
            page = context.new_page()
            note = "browser_context_ok"
            try:
                page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
                page.fill("#email", self.email)
                page.fill("#password", self.password)
                page.click("#login-submit")
                page.wait_for_url("**/dashboard", timeout=10000)
                page.screenshot(path=str(self.evidence_dir / "verifier_logged_in.png"))
                page.goto(f"{self.base_url}/invoices", wait_until="domcontentloaded")
                page.screenshot(path=str(self.evidence_dir / "verifier_invoices.png"))
            except Exception as exc:  # noqa: BLE001
                note = f"browser_scrape_error={exc}"
            state = context.storage_state()
            context.close()
            browser.close()
            pw.stop()
            return ctx_id, state, note

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run).result(timeout=120)

    def verify_invoices(self, invoices: list[InvoiceRecord]) -> VerificationResult:
        # Isolated browser probe (own cookies/storage) — never the executor context.
        try:
            self.context_id, self._last_storage, browser_note = self._probe_isolated_browser()
        except Exception as exc:  # noqa: BLE001
            self.context_id = None
            self._last_storage = {}
            browser_note = f"browser_probe_error={exc}"

        # Structured ground truth via fresh portal_api session (separate from browser).
        api_res = self._api.run({"action": "invoices"})
        portal_rows = list(api_res.data.get("result") or []) if api_res.ok else []

        by_number: dict[str, list[dict[str, object]]] = {}
        for row in portal_rows:
            by_number.setdefault(str(row.get("invoice_number")), []).append(row)

        criteria: list[CriterionResult] = []
        for inv in invoices:
            rows = by_number.get(inv.invoice_number, [])
            portal_row = None
            if rows:
                attachment = inv.attachment_name
                if attachment:
                    portal_row = next(
                        (
                            r
                            for r in rows
                            if str(r.get("attachment_name") or "") == attachment
                        ),
                        None,
                    )
                if portal_row is None:
                    canonical = inv.canonical_vendor or inv.vendor
                    portal_row = next(
                        (
                            r
                            for r in rows
                            if str(r.get("vendor") or "") in {inv.vendor, canonical}
                        ),
                        rows[0],
                    )
            criteria.extend(
                check_invoice_against_portal(inv, portal_row, all_rows_for_number=rows)
            )

        criteria.append(
            CriterionResult(
                name="verifier_context_isolated",
                passed=self.context_id is not None,
                detail=f"{browser_note}; context={self.context_id}",
            )
        )

        business = [c for c in criteria if c.name != "verifier_context_isolated"]
        passed = all(c.passed for c in business) if business else False
        conf = Confidence.HIGH if passed else Confidence.MEDIUM
        if not business:
            conf = Confidence.LOW
        return VerificationResult(
            passed=passed,
            confidence=conf,
            criteria=criteria,
            overall_notes=(
                f"{sum(1 for c in business if c.passed)}/{len(business)} checks passed; "
                f"{browser_note}"
            ),
        )


class Verifier(BrowserVerifier):
    """Alias: production verifier is always browser-isolated."""
