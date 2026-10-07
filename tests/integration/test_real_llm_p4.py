"""P4 AC with real Anthropic: understand+plan, then 12 decisions match expected_outcomes.

Skipped automatically when ANTHROPIC_API_KEY is absent (CI FakeLLM path).
Never logs or asserts on secret values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from ark_operator.config import clear_settings_cache, get_settings
from ark_operator.domain.models import InvoiceRecord, Plan
from ark_operator.llm.anthropic_client import AnthropicClient
from ark_operator.memory.knowledge import KnowledgeStore
from ark_operator.policy.engine import PolicyEngine
from ark_operator.runtime.pipeline import build_llm
from ark_operator.runtime.planner import Planner
from ark_operator.runtime.understand import Understander
from ark_operator.tools.pdf_extract import PdfExtractTool

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "company_world" / "inbox"
EXPECTED = json.loads((ROOT / "company_world" / "expected_outcomes.json").read_text())
REQUEST = "Process this month's pending vendor invoices."


def _has_anthropic_key() -> bool:
    clear_settings_cache()
    key = get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    return bool(key and len(key) > 8)


pytestmark = pytest.mark.skipif(
    not _has_anthropic_key(),
    reason="ANTHROPIC_API_KEY not set — FakeLLM CI path only",
)


@pytest.fixture
def engine(live_portal: str, monkeypatch: pytest.MonkeyPatch) -> PolicyEngine:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    clear_settings_cache()
    from ark_operator.tools.portal_api import PortalApiTool

    api = PortalApiTool(live_portal, email="operator@acmecorp.test", password="test-operator")
    try:
        vendors = api.run({"action": "vendors"}).data["result"]
        pos = api.run({"action": "pos"}).data["result"]
    finally:
        api.close()
    eng = PolicyEngine()
    eng.load_portal_master(vendors, pos)
    return eng


def test_real_llm_understand_plan_and_twelve_decisions(
    engine: PolicyEngine, tmp_path: Path
) -> None:
    """Real Haiku understand+plan; PolicyEngine decisions match expected_outcomes."""
    llm = build_llm(require_anthropic=True)
    assert isinstance(llm, AnthropicClient)
    assert "haiku" in llm.model.lower()

    ks = KnowledgeStore(tmp_path / "knowledge.db")
    ks.ingest(ROOT / "company_world" / "knowledge")
    hits = ks.search("invoice approval tolerance vendor duplicate security", top_k=6)

    interp = Understander(llm).interpret(REQUEST, knowledge_snippets=hits)
    assert interp.intended_outcome
    assert "invoice" in interp.intended_outcome.lower()
    # Must be a real model response, not the labeled STUB scaffold wording alone.
    assert len(interp.assumptions) >= 1
    assert len(interp.success_criteria) >= 1

    plan = Planner(llm).create_plan(interp)
    assert isinstance(plan, Plan)
    assert len(plan.steps) >= 3
    tools = {s.tool for s in plan.steps}
    # Top-level plan should cover discovery / process / verify shape.
    expected_tools = ("files", "knowledge_search", "orchestrator", "browser", "verifier")
    assert any(t in tools for t in expected_tools) or any(
        any(name in t for name in expected_tools) for t in tools
    )

    # P4 decision AC — deterministic policy over extracted invoices (LLM does not decide).
    pdf = PdfExtractTool()
    expected_by_number = {i["invoice_number"]: i for i in EXPECTED["invoices"]}
    mismatches: list[str] = []
    for n in range(1001, 1013):
        file_id = f"INV-{n}"
        extracted = pdf.run({"path": str(INBOX / f"{file_id}.pdf")})
        assert extracted.ok, extracted.failure
        inv = InvoiceRecord.model_validate(extracted.data["invoice"])
        inv.security_finding = bool(extracted.data.get("security_finding"))
        decided = engine.decide_invoice(inv)
        exp = expected_by_number[file_id]
        assert decided.decision is not None
        if decided.decision.value != exp["decision"]:
            mismatches.append(f"{file_id}: got {decided.decision.value} expected {exp['decision']}")
        if file_id == "INV-1010":
            assert inv.security_finding is True

    assert not mismatches, "P4 decision AC failed:\n" + "\n".join(mismatches)
