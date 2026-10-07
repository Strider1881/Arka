"""Extract invoice fields from PDFs via pdfplumber (+ optional LLM structuring)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ark_operator.domain.enums import Confidence, FailureKind, RiskLevel
from ark_operator.domain.models import Failure, InvoiceRecord, Observation
from ark_operator.security.envelope import prepare_for_llm
from ark_operator.tools.base import BaseTool, ToolResult


class PdfExtractTool(BaseTool):
    """PDF text extraction and structured Invoice parsing."""

    name = "pdf_extract"
    risk_class = RiskLevel.READ
    timeout_seconds = 30.0
    description = "Extract invoice fields from a PDF path"

    def _run(self, args: dict[str, Any]) -> ToolResult:
        path = Path(str(args["path"]))
        if not path.exists():
            return ToolResult(
                ok=False,
                failure=Failure(kind=FailureKind.UNRECOVERABLE, message=f"PDF not found: {path}"),
            )
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)

        invoice = _parse_invoice_text(text, attachment_name=path.name)
        wrapped, security = prepare_for_llm(text)
        invoice.security_finding = security
        return ToolResult(
            ok=True,
            observation=Observation(
                summary=f"Extracted {invoice.invoice_number}",
                data={"invoice": invoice.model_dump(mode="json"), "security_finding": security},
            ),
            data={
                "invoice": invoice.model_dump(mode="json"),
                # Never put raw unwrapped text into events/logs — only wrapped for LLM.
                "security_finding": security,
                "untrusted_wrapped": wrapped,
            },
        )


def _parse_invoice_text(text: str, *, attachment_name: str) -> InvoiceRecord:
    number = _match(text, r"Invoice Number:\s*(\S+)") or attachment_name.replace(".pdf", "")
    vendor = _match(text, r"Vendor:\s*(.+)") or ""
    amount_s = _match(text, r"Amount:\s*\$?([\d,]+\.\d{2})") or "0"
    amount = float(amount_s.replace(",", ""))
    po = _match(text, r"PO Number:\s*(\S+)")
    if po in (None, "N/A"):
        po = None
    date = _match(text, r"Invoice Date:\s*(\S+)") or ""
    return InvoiceRecord(
        invoice_number=number.strip(),
        vendor=vendor.strip(),
        amount=amount,
        po_number=po,
        invoice_date=date.strip(),
        attachment_name=attachment_name,
        confidence=Confidence.HIGH,
        fields_confidence={
            "invoice_number": 0.99,
            "vendor": 0.95,
            "amount": 0.99,
            "po_number": 0.9 if po else 0.5,
            "invoice_date": 0.95,
        },
    )


def _match(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None
