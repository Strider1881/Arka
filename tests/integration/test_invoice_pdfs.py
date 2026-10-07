"""All 12 invoice PDFs exist and extract cleanly via pdfplumber."""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest
from company_world.scripts.make_invoices import INJECTION_TEXT, INVOICES, generate_all

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "company_world" / "inbox"


@pytest.fixture(scope="module", autouse=True)
def _ensure_pdfs() -> None:
    generate_all(INBOX)


def test_twelve_pdfs_exist() -> None:
    paths = list(INBOX.glob("INV-*.pdf"))
    assert len(paths) == 12
    expected = {f"INV-{n}.pdf" for n in range(1001, 1013)}
    assert {p.name for p in paths} == expected


@pytest.mark.parametrize("inv", INVOICES, ids=lambda i: str(i["number"]))
def test_pdf_extracts_core_fields(inv: dict[str, object]) -> None:
    path = INBOX / f"{inv['number']}.pdf"
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert str(inv["number"]) in text
    assert str(inv["vendor"]) in text
    amount = float(inv["amount"])
    # reportlab formats with commas for thousands
    assert f"${amount:,.2f}" in text or f"${amount:.2f}" in text
    if inv["po"]:
        assert str(inv["po"]) in text
    assert str(inv["date"]) in text


def test_inv_1010_contains_injection_text() -> None:
    path = INBOX / "INV-1010.pdf"
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert INJECTION_TEXT in text
    assert "INV-1010" in text
    assert "Globex Industrial" in text
