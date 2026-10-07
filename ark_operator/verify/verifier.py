"""Independent verifier (separate portal_api session; agent never grades itself)."""

from __future__ import annotations

from ark_operator.domain.enums import Confidence
from ark_operator.domain.models import CriterionResult, InvoiceRecord, VerificationResult
from ark_operator.tools.portal_api import PortalApiTool
from ark_operator.verify.checks import check_invoice_against_portal


class Verifier:
    """Check portal ground truth against expected decisions using a fresh read client."""

    def __init__(self, portal_api: PortalApiTool) -> None:
        self.portal_api = portal_api

    def verify_invoices(self, invoices: list[InvoiceRecord]) -> VerificationResult:
        criteria: list[CriterionResult] = []
        res = self.portal_api.run({"action": "invoices"})
        portal_rows = list(res.data.get("result") or []) if res.ok else []
        by_number: dict[str, list[dict[str, object]]] = {}
        for row in portal_rows:
            by_number.setdefault(str(row.get("invoice_number")), []).append(row)

        for inv in invoices:
            rows = by_number.get(inv.invoice_number, [])
            # Prefer matching vendor / attachment when multiple rows share a number
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

        passed = all(c.passed for c in criteria) if criteria else False
        conf = Confidence.HIGH if passed else Confidence.MEDIUM
        if not criteria:
            conf = Confidence.LOW
        return VerificationResult(
            passed=passed,
            confidence=conf,
            criteria=criteria,
            overall_notes=f"{sum(1 for c in criteria if c.passed)}/{len(criteria)} checks passed",
        )
