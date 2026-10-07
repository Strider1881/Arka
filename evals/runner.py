"""Reset portal DB, run operator headless per scenario, write results."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import yaml
from ark_operator.events.store import EventStore
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from company_world.portal.app import create_app
from company_world.portal.db import reset_database
from company_world.portal.faults import fault_state

from evals.scoring import score

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def _start_portal(db_path: Path, port: int, password: str = "eval-pass") -> uvicorn.Server:
    os.environ["PORTAL_DB_PATH"] = str(db_path)
    os.environ["PORTAL_OPERATOR_PASSWORD"] = password
    os.environ["PORTAL_MANAGER_PASSWORD"] = "eval-manager"
    os.environ["FAULTS"] = ""
    fault_state.enabled = set()
    fault_state.flaky_test_force = False
    fault_state.session_request_counts.clear()
    fault_state.flaky_fired.clear()
    fault_state.submitted_fingerprints.clear()
    reset_database(db_path, operator_password=password, manager_password="eval-manager")
    app = create_app(reset_db=False)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            try:
                if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                    return server
            except Exception:
                pass
        time.sleep(0.05)
    raise RuntimeError("eval portal failed to start")


def load_scenarios() -> list[dict[str, Any]]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["_path"] = str(path)
        scenarios.append(data)
    return scenarios


def run_scenario(scenario: dict[str, Any], *, data_dir: Path) -> dict[str, Any]:
    port = _free_port()
    db = data_dir / f"portal-{scenario['id']}.db"
    password = "eval-pass"
    server = _start_portal(db, port, password=password)
    base = f"http://127.0.0.1:{port}"
    try:
        faults = scenario.get("faults") or []
        if faults:
            httpx.post(
                f"{base}/admin/faults",
                json={
                    "faults": faults,
                    "flaky_force": bool(scenario.get("flaky_force", False)),
                    "session_expiry_n": int(scenario.get("session_expiry_n", 5)),
                    "reset_counters": True,
                },
                timeout=5.0,
            )
        os.environ["PORTAL_OPERATOR_PASSWORD"] = password
        store = EventStore(data_dir / f"events-{scenario['id']}.db")
        auto = scenario.get("auto_approve")
        cfg = PipelineConfig(
            portal_base_url=base,
            data_dir=data_dir / scenario["id"],
            headless=True,
            auto_approve=auto,
            invoice_filter=scenario.get("invoice_filter"),
        )
        if scenario.get("crash_after_invoices") is not None:
            cfg.crash_after_invoices = int(scenario["crash_after_invoices"])
        pipe = InvoicePipeline(store, build_default_fake_llm(), cfg)
        t0 = time.monotonic()
        request = scenario.get("request") or "Process this month's pending vendor invoices."
        result = pipe.run(request)
        # Scenario 12: simulated crash mid-EXECUTE, then durable resume.
        if scenario.get("crash_after_invoices") is not None and result.state.value != "COMPLETE":
            cfg.crash_after_invoices = None
            pipe2 = InvoicePipeline(store, build_default_fake_llm(), cfg)
            result = pipe2.resume(result.run_id)
        wall = time.monotonic() - t0
        metrics = score(
            result,
            invoice_filter=scenario.get("invoice_filter"),
        )
        metrics["wall_time"] = wall
        metrics["scenario"] = scenario["id"]
        metrics["run_id"] = result.run_id
        metrics["state"] = result.state.value
        return metrics
    finally:
        server.should_exit = True


def run_all(*, only: list[str] | None = None) -> list[dict[str, Any]]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    data_dir = RESULTS_DIR / "_runs"
    data_dir.mkdir(exist_ok=True)
    results: list[dict[str, Any]] = []
    for scenario in load_scenarios():
        if only and scenario["id"] not in only:
            continue
        print(f"Running scenario {scenario['id']}...")
        metrics = run_scenario(scenario, data_dir=data_dir)
        results.append(metrics)
        print(
            f"  success={metrics['task_success']} "
            f"decisions={metrics['decisions_correct']}/{metrics['decisions_total']} "
            f"false_success={metrics['false_success_rate']}"
        )
    _write_summary(results)
    return results


def _write_summary(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Eval results",
        "",
        "| Scenario | task_success | decisions | false_success | unsafe | approvals_ok | recoveries | steps | wall_s |",
        "|----------|--------------|-----------|---------------|--------|--------------|------------|-------|--------|",
    ]
    for r in results:
        lines.append(
            f"| {r['scenario']} | {r['task_success']} | "
            f"{r['decisions_correct']}/{r['decisions_total']} | "
            f"{r['false_success_rate']:.2f} | {r.get('unsafe_actions', 0)} | "
            f"{r.get('approvals_requested_correctly', True)} | "
            f"{r.get('recoveries_used', 0)} | {r['steps']} | {r['wall_time']:.1f} |"
        )
    agg_success = all(r["task_success"] for r in results) if results else False
    lines.extend(
        [
            "",
            f"Aggregate task_success: **{agg_success}**",
            f"Aggregate false_success_rate max: "
            f"**{max((r['false_success_rate'] for r in results), default=0):.2f}**",
            f"Aggregate unsafe_actions max: "
            f"**{max((r.get('unsafe_actions', 0) for r in results), default=0)}**",
            "",
        ]
    )
    (RESULTS_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS_DIR / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="Scenario ids to run")
    args = parser.parse_args()
    run_all(only=args.only)


if __name__ == "__main__":
    main()
