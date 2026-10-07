"""CLI entrypoints: run, approve, status, replay, eval (SPEC §3)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ark_operator.events.replay import fold_working_state, replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm


def _store() -> EventStore:
    path = Path(os.environ.get("OPERATOR_DB_PATH", "data/operator.db"))
    return EventStore(path)


def cmd_run(args: argparse.Namespace) -> int:
    store = _store()
    cfg = PipelineConfig(
        portal_base_url=os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8765"),
        headless=os.environ.get("OPERATOR_HEADLESS", "true").lower() != "false",
        auto_approve=True if args.auto_approve else None,
        invoice_filter=args.only.split(",") if args.only else None,
    )
    pipe = InvoicePipeline(store, build_default_fake_llm(), cfg)
    result = pipe.run(args.request)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "state": result.state.value,
                "summary": result.report.summary if result.report else None,
                "pending_approvals": result.pending_approval_ids,
            },
            indent=2,
        )
    )
    return 0 if result.state.value == "COMPLETE" else 2


def cmd_approve(args: argparse.Namespace) -> int:
    store = _store()
    decision = "reject" if args.reject else "approve"
    info = store.decide_approval(args.approval_id, decision)
    if not info:
        print("Approval not found", file=sys.stderr)
        return 1
    store.append(
        info["run_id"],
        EventType.APPROVAL_DECIDED,
        {"approval_id": args.approval_id, "decision": decision, "info": info},
    )
    # Only the decided approval is applied; do not blanket-auto-approve the rest.
    cfg = PipelineConfig(
        portal_base_url=os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8765"),
        auto_approve=None,
    )
    InvoicePipeline(store, build_default_fake_llm(), cfg).resume(info["run_id"])
    print(json.dumps({"resumed": info["run_id"], "decision": info["status"]}))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = _store()
    working = fold_working_state(store, args.run_id)
    print(json.dumps(working.model_dump(mode="json"), indent=2))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    store = _store()
    print(json.dumps(replay_run(store, args.run_id), indent=2))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from evals.runner import run_all

    results = run_all(only=args.only)
    ok = all(r["task_success"] for r in results)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="operator", description="Operator CLI")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Start a run")
    p_run.add_argument("request")
    p_run.add_argument("--auto-approve", action="store_true")
    p_run.add_argument("--only", help="Comma-separated invoice file stems")
    p_run.set_defaults(func=cmd_run)

    p_ap = sub.add_parser("approve", help="Approve/reject a step")
    p_ap.add_argument("approval_id")
    p_ap.add_argument("--reject", action="store_true")
    p_ap.set_defaults(func=cmd_approve)

    p_st = sub.add_parser("status", help="Show run status")
    p_st.add_argument("run_id")
    p_st.set_defaults(func=cmd_status)

    p_rp = sub.add_parser("replay", help="Replay a run from events")
    p_rp.add_argument("run_id")
    p_rp.set_defaults(func=cmd_replay)

    p_ev = sub.add_parser("eval", help="Run evals")
    p_ev.add_argument("--only", nargs="*")
    p_ev.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
