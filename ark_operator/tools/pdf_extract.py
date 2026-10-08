"""Extract invoice fields from PDFs via pdfplumber + LLM-structured extraction (SPEC §6.8)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ark_operator.domain.enums import Confidence, FailureKind, RiskLevel
from ark_operator.domain.models import Failure, InvoiceRecord, Observation
from ark_operator.security.envelope import prepare_for_llm
from ark_operator.tools.base import BaseTool, ToolResult

LOW_CONFIDENCE = 0.7


class InvoiceExtractSchema(BaseModel):
    """Structured LLM extraction payload with per-field confidence."""

    invoice_number: str = ""
    vendor: str = ""
    amount: float = 0.0
    po_number: str | None = None
    invoice_date: str = ""
    fields_confidence: dict[str, float] = Field(default_factory=dict)
    needs_human: bool = False
    notes: str = ""


class PdfExtractTool(BaseTool):
    """PDF text extraction and structured Invoice parsing (LLM + regex fallback)."""

    name = "pdf_extract"
    risk_class = RiskLevel.READ
    timeout_seconds = 30.0
    description = "Extract invoice fields from a PDF path"

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

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

        wrapped, security = prepare_for_llm(text)
        invoice, meta = self._structure(text, wrapped, attachment_name=path.name)
        invoice.security_finding = security

        # Low confidence → one re-extract; still low → ask_human signal.
        if meta.get("low_confidence") and self.llm is not None and not meta.get("reextracted"):
            invoice2, meta2 = self._structure(
                text, wrapped, attachment_name=path.name, force_llm=True, reextract=True
            )
            invoice2.security_finding = security
            invoice, meta = invoice2, meta2

        return ToolResult(
            ok=True,
            observation=Observation(
                summary=f"Extracted {invoice.invoice_number}",
                data={
                    "invoice": invoice.model_dump(mode="json"),
                    "security_finding": security,
                    **{k: v for k, v in meta.items() if k != "invoice"},
                },
            ),
            data={
                "invoice": invoice.model_dump(mode="json"),
                "security_finding": security,
                "untrusted_wrapped": wrapped,
                "ask_human": bool(meta.get("ask_human")),
                "fields_confidence": invoice.fields_confidence,
                "extraction": meta,
            },
        )

    def _structure(
        self,
        text: str,
        wrapped: str,
        *,
        attachment_name: str,
        force_llm: bool = False,
        reextract: bool = False,
    ) -> tuple[InvoiceRecord, dict[str, Any]]:
        regex_inv = _parse_invoice_text(text, attachment_name=attachment_name)
        if self.llm is None and not force_llm:
            return regex_inv, {"method": "regex", "low_confidence": False, "reextracted": reextract}

        llm = self.llm
        if llm is None:
            return regex_inv, {"method": "regex", "low_confidence": False, "reextracted": reextract}
        try:
            resp = llm.complete(
                "invoice_extract",
                {
                    "untrusted_text": wrapped,
                    "attachment_name": attachment_name,
                    "reextract": reextract,
                    "regex_hint": regex_inv.model_dump(mode="json"),
                },
                schema=InvoiceExtractSchema,
            )
            content = resp.content
            if isinstance(content, InvoiceExtractSchema):
                parsed = content
            elif isinstance(content, dict):
                parsed = InvoiceExtractSchema.model_validate(content)
            else:
                return regex_inv, {"method": "regex_fallback", "low_confidence": False}

            conf = dict(parsed.fields_confidence or {})
            if not conf:
                conf = {
                    "invoice_number": 0.9 if parsed.invoice_number else 0.2,
                    "vendor": 0.9 if parsed.vendor else 0.2,
                    "amount": 0.9 if parsed.amount else 0.2,
                    "po_number": 0.85 if parsed.po_number else 0.4,
                    "invoice_date": 0.85 if parsed.invoice_date else 0.3,
                }
            low = any(float(v) < LOW_CONFIDENCE for v in conf.values()) or parsed.needs_human
            # Merge: prefer LLM fields when present, else regex.
            inv = InvoiceRecord(
                invoice_number=parsed.invoice_number or regex_inv.invoice_number,
                vendor=parsed.vendor or regex_inv.vendor,
                amount=parsed.amount if parsed.amount else regex_inv.amount,
                po_number=parsed.po_number if parsed.po_number is not None else regex_inv.po_number,
                invoice_date=parsed.invoice_date or regex_inv.invoice_date,
                attachment_name=attachment_name,
                confidence=Confidence.LOW if low else Confidence.HIGH,
                fields_confidence=conf,
            )
            ask = bool(parsed.needs_human or (low and reextract))
            return inv, {
                "method": "llm",
                "low_confidence": low,
                "ask_human": ask,
                "reextracted": reextract,
                "notes": parsed.notes,
            }
        except Exception as exc:  # noqa: BLE001
            return regex_inv, {
                "method": "regex_fallback",
                "low_confidence": False,
                "error": str(exc)[:200],
                "reextracted": reextract,
            }


def scripted_invoice_extract(variables: dict[str, Any]) -> dict[str, Any]:
    """FakeLLM script: structure from regex_hint with honest per-field confidence."""
    hint = variables.get("regex_hint") or {}
    reextract = bool(variables.get("reextract"))
    attachment = str(variables.get("attachment_name") or "")
    # Simulate low confidence once on first pass for empty/odd attachments.
    low_probe = attachment.endswith("LOWCONF.pdf") and not reextract
    conf = {
        "invoice_number": 0.99,
        "vendor": 0.95,
        "amount": 0.99,
        "po_number": 0.9 if hint.get("po_number") else 0.55,
        "invoice_date": 0.95,
    }
    if low_probe:
        conf = {k: 0.4 for k in conf}
    return {
        "invoice_number": hint.get("invoice_number") or "",
        "vendor": hint.get("vendor") or "",
        "amount": float(hint.get("amount") or 0),
        "po_number": hint.get("po_number"),
        "invoice_date": hint.get("invoice_date") or "",
        "fields_confidence": conf,
        "needs_human": low_probe and reextract,
        "notes": "scripted_invoice_extract",
    }


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
