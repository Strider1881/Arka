"""Reset portal DB, run operator headless per scenario, write results."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import yaml
from ark_operator.config import clear_settings_cache, get_settings
from ark_operator.events.store import EventStore
from ark_operator.memory.episodic import EpisodicMemory
from ark_operator.runtime.browser_loop import scripted_browser_step
from ark_operator.runtime.pipeline import (
    InvoicePipeline,
    PipelineConfig,
    build_default_fake_llm,
    build_llm,
)
from company_world.portal.app import create_app
from company_world.portal.db import reset_database
from company_world.portal.faults import fault_state

from evals.scoring import score

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Shared with portal admin gate for headless evals (never a production secret).
EVAL_ADMIN_TOKEN = "eval-admin-token"

# Real-Haiku subset for `make eval-llm` (a11y loop; no FakeLLM).
DEFAULT_LLM_SCENARIOS = [
    "01-happy",
    "03-session-expiry",
    "04-ui-rename",
    "05-approval-granted",
    "06-approval-rejected",
]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def _admin_headers() -> dict[str, str]:
    return {"x-portal-admin-token": os.environ.get("PORTAL_ADMIN_TOKEN", EVAL_ADMIN_TOKEN)}


def _start_portal(db_path: Path, port: int, password: str = "eval-pass") -> uvicorn.Server:
    os.environ["PORTAL_DB_PATH"] = str(db_path)
    os.environ["PORTAL_OPERATOR_PASSWORD"] = password
    os.environ["PORTAL_MANAGER_PASSWORD"] = "eval-manager"
    os.environ.setdefault("PORTAL_ADMIN_TOKEN", EVAL_ADMIN_TOKEN)
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


def _require_anthropic_key() -> None:
    """Fail clearly when eval-llm is invoked without a real API key."""
    clear_settings_cache()
    settings = get_settings()
    key = (settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        print(
            "ERROR: make eval-llm requires ANTHROPIC_API_KEY "
            "(set in `.env` or the environment). "
            "This path never falls back to FakeLLM. "
            "Use `make eval` for the FakeLLM CI path.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _build_eval_llm(*, clarify: bool = False, real_llm: bool = False) -> Any:
    """FakeLLM (CI) or Anthropic Haiku (eval-llm). Never mix the two."""
    if real_llm:
        return build_llm(require_anthropic=True)
    llm = build_default_fake_llm()
    llm.register("browser_step", scripted_browser_step)
    if clarify:
        from ark_operator.domain.models import Interpretation, PolicyCitation

        llm.register(
            "understand",
            Interpretation(
                intended_outcome="Process pending vendor invoices with policy and proof",
                assumptions=[],
                sources_needed=["inbox", "knowledge", "portal"],
                applicable_policies=[
                    PolicyCitation(file="invoice_processing_sop.md", section="Three-way match")
                ],
                permitted_actions=["extract", "submit", "ask_human", "verify"],
                success_criteria=["Portal matches decisions", "Verifier passes"],
                open_questions=[
                    "INV-1006 has no matching PO — provide a PO number or reject the invoice?"
                ],
            ),
        )
    # Structured PDF extraction script (SPEC §6.8) — FakeLLM path.
    from ark_operator.tools.pdf_extract import scripted_invoice_extract

    llm.register("invoice_extract", scripted_invoice_extract)
    return llm


def run_scenario(
    scenario: dict[str, Any],
    *,
    data_dir: Path,
    use_browser_loop: bool = True,
    real_llm: bool = False,
) -> dict[str, Any]:
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
                headers=_admin_headers(),
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
        scenario_dir = data_dir / scenario["id"]
        scenario_dir.mkdir(parents=True, exist_ok=True)
        # Fresh episodic per scenario so recovery/learning metrics are honest.
        episodic = EpisodicMemory(scenario_dir / "episodic.db")
        episodic.clear()
        auto = scenario.get("auto_approve")
        cfg = PipelineConfig(
            portal_base_url=base,
            data_dir=scenario_dir,
            headless=True,
            auto_approve=auto,
            invoice_filter=scenario.get("invoice_filter"),
            use_browser_loop=use_browser_loop,
            # Real-LLM path: no silent RPA repair after a11y miss.
            allow_rpa_repair=not real_llm,
            force_clarify=bool(scenario.get("clarify", False)),
        )
        if scenario.get("crash_after_invoices") is not None:
            cfg.crash_after_invoices = int(scenario["crash_after_invoices"])
        llm = _build_eval_llm(clarify=bool(scenario.get("clarify", False)), real_llm=real_llm)
        pipe = InvoicePipeline(store, llm, cfg, episodic=episodic)
        t0 = time.monotonic()
        request = scenario.get("request") or "Process this month's pending vendor invoices."
        result = pipe.run(request)
        if scenario.get("crash_after_invoices") is not None and result.state.value != "COMPLETE":
            cfg.crash_after_invoices = None
            pipe2 = InvoicePipeline(
                store,
                _build_eval_llm(real_llm=real_llm),
                cfg,
                episodic=episodic,
            )
            result = pipe2.resume(result.run_id)
        wall = time.monotonic() - t0
        metrics = score(
            result,
            invoice_filter=scenario.get("invoice_filter"),
            store=store,
        )
        metrics["wall_time"] = wall
        metrics["scenario"] = scenario["id"]
        metrics["run_id"] = result.run_id
        metrics["state"] = result.state.value
        metrics["browser_path"] = "a11y_loop" if use_browser_loop else "rpa_shortcut"
        metrics["llm_path"] = "anthropic" if real_llm else "fakellm"
        if real_llm:
            settings = get_settings()
            metrics["operator_model"] = settings.operator_model
        return metrics
    finally:
        server.should_exit = True


def run_all(
    *,
    only: list[str] | None = None,
    use_browser_loop: bool = True,
    real_llm: bool = False,
    retries: int = 0,
) -> list[dict[str, Any]]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    data_dir = RESULTS_DIR / ("_runs_llm" if real_llm else "_runs")
    data_dir.mkdir(exist_ok=True)
    results: list[dict[str, Any]] = []
    for scenario in load_scenarios():
        if only and scenario["id"] not in only:
            continue
        path = "a11y_loop" if use_browser_loop else "rpa_shortcut"
        llm_label = "Haiku" if real_llm else "FakeLLM"
        print(f"Running scenario {scenario['id']} ({path}, {llm_label})...")
        metrics = run_scenario(
            scenario,
            data_dir=data_dir,
            use_browser_loop=use_browser_loop,
            real_llm=real_llm,
        )
        attempt = 0
        while real_llm and retries > 0 and not metrics["task_success"] and attempt < retries:
            attempt += 1
            print(
                f"  retry {attempt}/{retries} after task_success=False "
                f"(scenario={scenario['id']})..."
            )
            metrics = run_scenario(
                scenario,
                data_dir=data_dir,
                use_browser_loop=use_browser_loop,
                real_llm=real_llm,
            )
            metrics["retried"] = attempt
        results.append(metrics)
        cost = metrics.get("cost_usd")
        cost_s = f"{cost:.4f}" if isinstance(cost, (int, float)) else "—"
        print(
            f"  success={metrics['task_success']} "
            f"decisions={metrics['decisions_correct']}/{metrics['decisions_total']} "
            f"false_success={metrics['false_success_rate']} "
            f"recoveries={metrics.get('recoveries_used', 0)} "
            f"cost_usd={cost_s}"
        )
    _write_summary(results, use_browser_loop=use_browser_loop, real_llm=real_llm)
    return results


def _write_summary(
    results: list[dict[str, Any]],
    *,
    use_browser_loop: bool,
    real_llm: bool = False,
) -> None:
    if real_llm:
        model = next(
            (r.get("operator_model") for r in results if r.get("operator_model")),
            get_settings().operator_model,
        )
        path_label = f"a11y_loop + Anthropic ({model}) — make eval-llm"
        md_name = "summary-llm.md"
        json_name = "summary-llm.json"
    else:
        path_label = (
            "a11y_loop (default make eval)" if use_browser_loop else "rpa_shortcut (make eval-rpa)"
        )
        md_name = "summary.md"
        json_name = "summary.json"
    lines = [
        "# Eval results" + (" (real LLM)" if real_llm else ""),
        "",
        f"**Measured path:** `{path_label}`",
        "",
    ]
    if real_llm:
        lines.extend(
            [
                "No FakeLLM. RPA repair after a11y miss is **disabled** on this path.",
                "",
            ]
        )
    lines.extend(
        [
            (
                "| Scenario | task_success | decisions | false_success | unsafe | "
                "approvals_ok | recoveries | steps | cost_usd | wall_s |"
            ),
            (
                "|----------|--------------|-----------|---------------|--------|"
                "--------------|------------|-------|----------|--------|"
            ),
        ]
    )
    for r in results:
        cost = r.get("cost_usd")
        cost_s = f"{cost:.4f}" if isinstance(cost, (int, float)) else "—"
        lines.append(
            f"| {r['scenario']} | {r['task_success']} | "
            f"{r['decisions_correct']}/{r['decisions_total']} | "
            f"{r['false_success_rate']:.2f} | {r.get('unsafe_actions', 0)} | "
            f"{r.get('approvals_requested_correctly', True)} | "
            f"{r.get('recoveries_used', 0)} | {r['steps']} | {cost_s} | "
            f"{r['wall_time']:.1f} |"
        )
    agg_success = all(r["task_success"] for r in results) if results else False
    n_ok = sum(1 for r in results if r["task_success"])
    cost_vals = [
        float(r["cost_usd"]) for r in results if isinstance(r.get("cost_usd"), (int, float))
    ]
    lines.extend(
        [
            "",
            f"Aggregate task_success: **{agg_success}** ({n_ok}/{len(results)})",
            f"Aggregate false_success_rate max: "
            f"**{max((r['false_success_rate'] for r in results), default=0):.2f}**",
            f"Aggregate unsafe_actions max: "
            f"**{max((r.get('unsafe_actions', 0) for r in results), default=0)}**",
        ]
    )
    if cost_vals:
        lines.append(f"Aggregate cost_usd sum: **{sum(cost_vals):.4f}**")
    lines.append("")
    (RESULTS_DIR / md_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS_DIR / json_name).write_text(json.dumps(results, indent=2), encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="Scenario ids to run")
    parser.add_argument(
        "--rpa",
        action="store_true",
        help="Use submit_invoice RPA shortcut instead of a11y browser loop",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help=(
            "Real Anthropic Haiku path (requires ANTHROPIC_API_KEY). "
            "Default subset: happy, session-expiry, ui-rename, approval granted/rejected. "
            "Never falls back to FakeLLM."
        ),
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="On --llm, retry each failed scenario this many times (default 1)",
    )
    args = parser.parse_args()
    if args.llm and args.rpa:
        print("ERROR: --llm implies a11y loop; do not combine with --rpa.", file=sys.stderr)
        raise SystemExit(2)
    if args.llm:
        _require_anthropic_key()
        only = args.only if args.only else list(DEFAULT_LLM_SCENARIOS)
        results = run_all(
            only=only,
            use_browser_loop=True,
            real_llm=True,
            retries=max(0, args.retries),
        )
    else:
        results = run_all(only=args.only, use_browser_loop=not args.rpa, real_llm=False)
    ok = all(r["task_success"] for r in results) if results else False
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
