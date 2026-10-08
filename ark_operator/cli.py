"""CLI entrypoints: run, approve, status, replay, eval (SPEC §3)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ark_operator.config import get_settings
from ark_operator.events.replay import fold_working_state, replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_llm


def _store() -> EventStore:
    settings = get_settings()
    return EventStore(Path(settings.operator_db_path))


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = _store()
    cfg = PipelineConfig(
        portal_base_url=settings.portal_base_url,
        headless=settings.operator_headless,
        auto_approve=True if args.auto_approve else None,
        invoice_filter=args.only.split(",") if args.only else None,
        use_browser_loop=None if args.browser_loop is None else args.browser_loop,
    )
    pipe = InvoicePipeline(store, build_llm(), cfg)
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


def _resolve_approval_id(store: EventStore, run_id: str, step: str | None) -> str | None:
    """Resolve SPEC-shaped `approve <run_id> --step <id>` to an approval id."""
    pending = store.pending_approvals(run_id)
    if not pending:
        return None
    if step:
        for row in pending:
            ctx = row.get("context") or {}
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except json.JSONDecodeError:
                    ctx = {}
            if (
                str(row.get("id")) == step
                or str(ctx.get("file_id") or "") == step
                or str(ctx.get("invoice_number") or "") == step
                or str(row.get("step_id") or "") == step
            ):
                return str(row["id"])
        return None
    return str(pending[0]["id"])


def cmd_approve(args: argparse.Namespace) -> int:
    """SPEC §3: `operator approve <run_id> --step <id> [--reject]`.

    Also accepts legacy `operator approve <approval_id>` when the arg looks like
    an approval UUID and --step is omitted (documented in DECISIONS.md).
    """
    store = _store()
    decision = "reject" if args.reject else "approve"
    run_id = args.run_id
    approval_id: str | None = None

    # Legacy: single positional was approval_id.
    if args.step is None:
        info = store.get_approval(run_id)
        if info:
            approval_id = run_id
            run_id = str(info["run_id"])
        else:
            approval_id = _resolve_approval_id(store, run_id, None)
    else:
        approval_id = _resolve_approval_id(store, run_id, args.step)

    if not approval_id:
        print("Approval not found", file=sys.stderr)
        return 1
    info = store.decide_approval(approval_id, decision)
    if not info:
        print("Approval not found", file=sys.stderr)
        return 1
    store.append(
        info["run_id"],
        EventType.APPROVAL_DECIDED,
        {"approval_id": approval_id, "decision": decision, "info": info},
    )
    settings = get_settings()
    cfg = PipelineConfig(
        portal_base_url=settings.portal_base_url,
        auto_approve=None,
    )
    InvoicePipeline(store, build_llm(), cfg).resume(info["run_id"])
    print(
        json.dumps(
            {"resumed": info["run_id"], "decision": info["status"], "approval_id": approval_id}
        )
    )
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
    from evals.runner import DEFAULT_LLM_SCENARIOS, _require_anthropic_key, run_all

    if getattr(args, "llm", False):
        if args.rpa:
            print("ERROR: --llm implies a11y loop; do not combine with --rpa.", file=sys.stderr)
            return 2
        _require_anthropic_key()
        only = args.only if args.only else list(DEFAULT_LLM_SCENARIOS)
        results = run_all(
            only=only,
            use_browser_loop=True,
            real_llm=True,
            retries=1,
        )
    else:
        results = run_all(only=args.only, use_browser_loop=not args.rpa, real_llm=False)
    ok = all(r["task_success"] for r in results)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="operator", description="Operator CLI")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Start a run")
    p_run.add_argument("request")
    p_run.add_argument("--auto-approve", action="store_true")
    p_run.add_argument("--only", help="Comma-separated invoice file stems")
    p_run.add_argument(
        "--browser-loop",
        dest="browser_loop",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force a11y browser loop (default) or --no-browser-loop for RPA shortcut",
    )
    p_run.set_defaults(func=cmd_run)

    p_ap = sub.add_parser("approve", help="Approve/reject a step (SPEC: run_id --step)")
    p_ap.add_argument("run_id", help="Run id (or legacy approval_id)")
    p_ap.add_argument(
        "--step",
        help="Step/file_id/invoice_number/approval_id to decide (defaults to first pending)",
    )
    p_ap.add_argument("--reject", action="store_true")
    p_ap.set_defaults(func=cmd_approve)

    p_st = sub.add_parser("status", help="Show run status")
    p_st.add_argument("run_id")
    p_st.set_defaults(func=cmd_status)

    p_rp = sub.add_parser("replay", help="Replay a run from events")
    p_rp.add_argument("run_id")
    p_rp.set_defaults(func=cmd_replay)

    p_ev = sub.add_parser("eval", help="Run evals (default: a11y browser loop)")
    p_ev.add_argument("--only", nargs="*")
    p_ev.add_argument("--rpa", action="store_true", help="Use RPA shortcut path")
    p_ev.add_argument(
        "--llm",
        action="store_true",
        help="Real Anthropic Haiku subset (requires ANTHROPIC_API_KEY; no FakeLLM)",
    )
    p_ev.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
