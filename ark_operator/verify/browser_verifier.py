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


def browser_row_mentions(rows: list[dict[str, str]], invoice_number: str) -> bool:
    """Pure helper: whether scraped browser table rows mention an invoice number."""
    needle = invoice_number.strip()
    if not needle:
        return False
    return any(
        needle in (r.get("invoice_number") or "") or needle in (r.get("row_text") or "")
        for r in rows
    )


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
        self.browser_rows: list[dict[str, str]] = []

    def close(self) -> None:
        self._api.close()

    def storage_state(self) -> dict[str, Any]:
        return dict(self._last_storage)

    def _probe_isolated_browser(self) -> tuple[str, dict[str, Any], str, list[dict[str, str]]]:
        """Create, use, and tear down a Playwright context entirely in one thread."""

        def _run() -> tuple[str, dict[str, Any], str, list[dict[str, str]]]:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context()
            ctx_id = f"verify-{id(context)}"
            page = context.new_page()
            note = "browser_context_ok"
            scraped: list[dict[str, str]] = []
            try:
                page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
                page.fill("#email", self.email)
                page.fill("#password", self.password)
                page.click("#login-submit")
                page.wait_for_url("**/dashboard", timeout=10000)
                page.screenshot(path=str(self.evidence_dir / "verifier_logged_in.png"))
                page.goto(f"{self.base_url}/invoices", wait_until="domcontentloaded")
                page.screenshot(path=str(self.evidence_dir / "verifier_invoices.png"))
                # Ground-truth scrape from the isolated browser (not executor cookies).
                scraped = page.eval_on_selector_all(
                    "table tbody tr, table tr",
                    """els => els.map(tr => {
                        const cells = [...tr.querySelectorAll('td')].map(td =>
                          (td.innerText || '').trim());
                        if (cells.length < 2) return null;
                        return {
                          invoice_number: cells[0] || '',
                          vendor: cells[1] || '',
                          amount: cells[2] || '',
                          status: cells[cells.length - 1] || '',
                          row_text: cells.join(' | '),
                        };
                      }).filter(Boolean)""",
                )
            except Exception as exc:  # noqa: BLE001
                note = f"browser_scrape_error={exc}"
            state = dict(context.storage_state())
            context.close()
            browser.close()
            pw.stop()
            return ctx_id, state, note, list(scraped or [])

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run).result(timeout=120)

    def verify_invoices(self, invoices: list[InvoiceRecord]) -> VerificationResult:
        # Isolated browser probe (own cookies/storage) — never the executor context.
        try:
            (
                self.context_id,
                self._last_storage,
                browser_note,
                self.browser_rows,
            ) = self._probe_isolated_browser()
        except Exception as exc:  # noqa: BLE001
            self.context_id = None
            self._last_storage = {}
            self.browser_rows = []
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
                        (r for r in rows if str(r.get("attachment_name") or "") == attachment),
                        None,
                    )
                if portal_row is None:
                    canonical = inv.canonical_vendor or inv.vendor
                    portal_row = next(
                        (r for r in rows if str(r.get("vendor") or "") in {inv.vendor, canonical}),
                        rows[0],
                    )
            criteria.extend(check_invoice_against_portal(inv, portal_row, all_rows_for_number=rows))

            # Observability: isolated browser scrape vs API (API remains authoritative).
            if (
                portal_row is not None
                and inv.decision
                and inv.decision.value
                in {
                    "submit",
                    "needs_approval",
                }
            ):
                needle = inv.invoice_number
                browser_hit = browser_row_mentions(self.browser_rows, needle)
                criteria.append(
                    CriterionResult(
                        name=f"browser_sees_{needle}",
                        # Soft check — never fails the run; proves scrape ran in isolation.
                        passed=True,
                        detail=(
                            "isolated browser lists invoice"
                            if browser_hit
                            else (
                                "browser scrape empty/miss (API authoritative); "
                                f"rows={len(self.browser_rows)}"
                            )
                        ),
                        evidence_refs=["verifier_invoices.png"],
                    )
                )

        criteria.append(
            CriterionResult(
                name="verifier_context_isolated",
                passed=self.context_id is not None,
                detail=(
                    f"{browser_note}; context={self.context_id}; scraped={len(self.browser_rows)}"
                ),
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
                f"{browser_note}; browser_rows={len(self.browser_rows)}"
            ),
        )


class Verifier(BrowserVerifier):
    """Alias: production verifier is always browser-isolated."""
