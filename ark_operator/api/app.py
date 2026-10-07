"""FastAPI application for the Operator UI/API (HTMX + SSE)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ark_operator.events.replay import fold_working_state, replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm

TEMPLATES_DIR = Path(__file__).resolve().parent / "ui" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DATA_DIR = Path(os.environ.get("OPERATOR_DATA_DIR", "data/ui"))
STORE_PATH = DATA_DIR / "operator.db"


def get_store() -> EventStore:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return EventStore(STORE_PATH)


def create_operator_app() -> FastAPI:
    app = FastAPI(title="Operator", version="0.2.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "phase": "P9"}

    @app.get("/", response_class=HTMLResponse)
    def handoff(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "handoff.html",
            {
                "request": request,
                "default_request": "Process this month's pending vendor invoices.",
            },
        )

    @app.post("/runs")
    def start_run(goal: str = Form(...)) -> RedirectResponse:
        store = get_store()
        cfg = PipelineConfig(
            portal_base_url=os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8765"),
            data_dir=DATA_DIR / "runs",
            headless=os.environ.get("OPERATOR_HEADLESS", "true").lower() != "false",
            auto_approve=None,
        )
        result = InvoicePipeline(store, build_default_fake_llm(), cfg).run(goal)
        return RedirectResponse(f"/runs/{result.run_id}", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_view(request: Request, run_id: str) -> HTMLResponse:
        store = get_store()
        working = fold_working_state(store, run_id)
        events = store.list_for_run(run_id)
        report = None
        for ev in reversed(events):
            if ev.type == EventType.REPORT_CREATED:
                report = ev.payload
                break
        approvals = store.pending_approvals(run_id)
        template = (
            "proof.html"
            if working.state in {"COMPLETE", "FAILED", "ESCALATED"} and report
            else "work.html"
        )
        return templates.TemplateResponse(
            request,
            template,
            {
                "request": request,
                "run_id": run_id,
                "working": working,
                "report": report,
                "approvals": approvals,
                "timeline": replay_run(store, run_id)[-30:],
            },
        )

    @app.post("/runs/{run_id}/approvals/{approval_id}")
    def decide(run_id: str, approval_id: str, decision: str = Form(...)) -> RedirectResponse:
        store = get_store()
        store.decide_approval(approval_id, decision, decided_by="ui")
        store.append(
            run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": approval_id, "decision": decision},
        )
        cfg = PipelineConfig(
            portal_base_url=os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8765"),
            data_dir=DATA_DIR / "runs",
            headless=True,
            auto_approve=decision.lower().startswith("approve"),
        )
        InvoicePipeline(store, build_default_fake_llm(), cfg).resume(run_id)
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}/details", response_class=HTMLResponse)
    def details(request: Request, run_id: str) -> HTMLResponse:
        store = get_store()
        return templates.TemplateResponse(
            request,
            "details.html",
            {"request": request, "run_id": run_id, "timeline": replay_run(store, run_id)},
        )

    @app.get("/runs/{run_id}/events")
    async def sse(run_id: str) -> StreamingResponse:
        store = get_store()

        async def gen() -> Any:
            last = 0
            for _ in range(120):
                events = store.list_for_run(run_id)
                if len(events) > last:
                    for ev in events[last:]:
                        yield (
                            "data: "
                            + json.dumps(
                                {"seq": ev.seq, "type": ev.type.value, "step_id": ev.step_id}
                            )
                            + "\n\n"
                        )
                    last = len(events)
                working = fold_working_state(store, run_id)
                if working.state in {"COMPLETE", "FAILED", "ESCALATED"}:
                    yield ("data: " + json.dumps({"type": "DONE", "state": working.state}) + "\n\n")
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


app = create_operator_app()
