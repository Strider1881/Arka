"""Headless 90s demo story: fault + approval pause/seeded decide + verifier catch/proof."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from company_world.portal.app import create_app
from company_world.portal.db import reset_database
from company_world.portal.faults import fault_state

from ark_operator.domain.enums import InvoiceDecision, InvoiceOutcome
from ark_operator.domain.models import InvoiceRecord
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from ark_operator.verify.verifier import Verifier


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    return int(s.getsockname()[1])


def _wait_health(base: str, server: uvicorn.Server) -> None:
    for _ in range(100):
        if server.started:
            try:
                if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                    return
            except Exception:
                pass
        time.sleep(0.05)
    raise RuntimeError("demo portal failed to start")


def main() -> int:
    """
    Narrative (aligned with DEMO.md):
      1) Seed ui_rename fault + run INV-1012 (recovery)
      2) Approval pause on INV-1003 → seeded decide → resume submit
      3) Verifier sabotage catch (false claim without portal row)
      4) Happy submit INV-1001 with proof
    """
    data = Path("data/demo")
    data.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("PORTAL_OPERATOR_PASSWORD", "demo-operator")
    admin = os.environ.get("PORTAL_ADMIN_TOKEN", "demo-admin-token")
    os.environ["PORTAL_OPERATOR_PASSWORD"] = password
    os.environ["PORTAL_MANAGER_PASSWORD"] = os.environ.get(
        "PORTAL_MANAGER_PASSWORD", "demo-manager"
    )
    os.environ["PORTAL_ADMIN_TOKEN"] = admin

    # Prefer an already-running portal when PORTAL_BASE_URL is reachable; else spawn one.
    base = os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    server: uvicorn.Server | None = None
    try:
        httpx.get(f"{base}/health", timeout=0.5).raise_for_status()
        print(f"[demo] using existing portal {base}")
    except Exception:
        port = _free_port()
        db = data / "portal.db"
        os.environ["PORTAL_DB_PATH"] = str(db)
        fault_state.enabled = set()
        reset_database(db, operator_password=password, manager_password="demo-manager")
        app = create_app(reset_db=False)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        _wait_health(base, server)
        print(f"[demo] started portal {base}")

    headers = {"x-portal-admin-token": admin}
    store = EventStore(data / "events.db")
    llm = build_default_fake_llm()

    print("\n=== 1) Fault + recovery (ui_rename / INV-1012) ===")
    httpx.post(
        f"{base}/admin/faults",
        headers=headers,
        json={"faults": ["ui_rename"], "reset_counters": True},
        timeout=5,
    )
    cfg = PipelineConfig(
        portal_base_url=base,
        data_dir=data / "fault",
        auto_approve=True,
        invoice_filter=["INV-1012"],
        use_browser_loop=True,
    )
    r1 = InvoicePipeline(store, llm, cfg).run("Process this month's pending vendor invoices.")
    recoveries = sum(
        1 for e in store.list_for_run(r1.run_id) if e.type == EventType.RECOVERY_ATTEMPTED
    )
    verified = bool(r1.verification and r1.verification.passed)
    print(f"  state={r1.state.value} recoveries={recoveries} verified={verified}")

    print("\n=== 2) Approval pause → seeded decide (INV-1003) ===")
    httpx.post(
        f"{base}/admin/faults",
        headers=headers,
        json={"faults": [], "reset_counters": True},
        timeout=5,
    )
    cfg2 = PipelineConfig(
        portal_base_url=base,
        data_dir=data / "approval",
        auto_approve=None,
        invoice_filter=["INV-1003"],
        use_browser_loop=True,
    )
    r2 = InvoicePipeline(store, llm, cfg2).run("Process this month's pending vendor invoices.")
    print(f"  paused state={r2.state.value} pending={r2.pending_approval_ids}")
    if not r2.pending_approval_ids:
        print("  ERROR: expected approval pause", file=sys.stderr)
        return 1
    aid = r2.pending_approval_ids[0]
    store.decide_approval(aid, "approve", decided_by="demo-seed")
    store.append(
        r2.run_id,
        EventType.APPROVAL_DECIDED,
        {"approval_id": aid, "decision": "approve"},
    )
    r2b = InvoicePipeline(store, llm, cfg2).resume(r2.run_id)
    print(
        f"  resumed state={r2b.state.value} verified={r2b.verification and r2b.verification.passed}"
    )

    print("\n=== 3) Verifier catch (sabotage: claim completed without portal row) ===")
    fake = InvoiceRecord(
        invoice_number="INV-SABOTAGE",
        vendor="Northwind Supplies",
        amount=10.0,
        po_number="PO-501",
        decision=InvoiceDecision.SUBMIT,
        outcome=InvoiceOutcome.COMPLETED,
        canonical_vendor="Northwind Supplies",
    )
    verifier = Verifier(base, evidence_dir=data / "sabotage-evidence", password=password)
    try:
        # Also sabotage browser scrape emptiness for submit-class hard-fail.
        verification = verifier.verify_invoices([fake])
    finally:
        verifier.close()
    print(f"  sabotage_passed={verification.passed} (expect False)")
    if verification.passed:
        print("  ERROR: verifier failed to catch sabotage", file=sys.stderr)
        return 1

    print("\n=== 4) Proof path (INV-1001 submit + verify) ===")
    cfg3 = PipelineConfig(
        portal_base_url=base,
        data_dir=data / "proof",
        auto_approve=True,
        invoice_filter=["INV-1001"],
        use_browser_loop=True,
    )
    r3 = InvoicePipeline(store, llm, cfg3).run("Process this month's pending vendor invoices.")
    print(
        json.dumps(
            {
                "run_id": r3.run_id,
                "state": r3.state.value,
                "summary": r3.report.summary if r3.report else None,
                "verification_passed": bool(r3.verification and r3.verification.passed),
            },
            indent=2,
        )
    )

    print("\n[demo] 90s story complete.")
    return 0 if r3.state.value == "COMPLETE" and r1.state.value == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
