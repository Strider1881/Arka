"""FastAPI application for the Operator UI/API (HTMX + SSE)."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ark_operator.config import get_settings
from ark_operator.events.replay import fold_working_state, replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.orchestrator import Orchestrator
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_llm
from ark_operator.verify.evidence import collect_run_evidence

TEMPLATES_DIR = Path(__file__).resolve().parent / "ui" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _data_dir() -> Path:
    return Path(get_settings().operator_data_dir)


def get_store() -> EventStore:
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return EventStore(data_dir / "operator.db")


def _pipeline_cfg(*, auto_approve: bool | None = None) -> PipelineConfig:
    settings = get_settings()
    return PipelineConfig(
        portal_base_url=settings.portal_base_url,
        data_dir=_data_dir() / "runs",
        headless=settings.operator_headless,
        auto_approve=auto_approve,
    )


def _invoice_checklist(store: EventStore, run_id: str) -> list[dict[str, str]]:
    """Calm progress list for Screen 2 — derived from events only."""
    rows: dict[str, dict[str, str]] = {}
    for ev in store.list_for_run(run_id):
        if not ev.step_id or ":act" not in ev.step_id:
            continue
        file_id = ev.step_id.split(":")[0]
        row = rows.setdefault(file_id, {"id": file_id, "status": "pending"})
        if ev.type == EventType.STEP_STARTED:
            row["status"] = "working"
            if ev.payload.get("decision"):
                row["decision"] = str(ev.payload["decision"])
        elif ev.type == EventType.STEP_COMPLETED:
            row["status"] = "done"
            if ev.payload.get("decision"):
                row["decision"] = str(ev.payload["decision"])
            if ev.payload.get("outcome"):
                row["outcome"] = str(ev.payload["outcome"])
        elif ev.type == EventType.STEP_FAILED:
            row["status"] = "failed"
    return list(rows.values())


def _evidence_thumbs(run_id: str, report: dict[str, Any] | None) -> list[dict[str, str]]:
    thumbs: list[dict[str, str]] = []
    seen: set[str] = set()
    if report:
        for item in report.get("evidence") or []:
            path = str(item.get("path") or "")
            label = str(item.get("label") or item.get("id") or Path(path).stem)
            if not path or path in seen:
                continue
            seen.add(path)
            thumbs.append(
                {
                    "label": label,
                    "url": f"/runs/{run_id}/evidence?path={path}",
                }
            )
    if thumbs:
        return thumbs[:24]
    # Fallback: scan known evidence roots for this run.
    roots = [
        _data_dir() / "runs" / "evidence" / run_id,
        _data_dir() / "runs" / "verify-evidence" / run_id,
        _data_dir() / "evidence" / run_id,
        _data_dir() / "verify-evidence" / run_id,
    ]
    for ev in collect_run_evidence(*roots):
        if ev.path in seen:
            continue
        seen.add(ev.path)
        thumbs.append({"label": ev.label, "url": f"/runs/{run_id}/evidence?path={ev.path}"})
    return thumbs[:24]


def _safe_evidence_path(raw: str) -> Path:
    """Resolve evidence path only under operator data dir (no path escape)."""
    data = _data_dir().resolve()
    path = Path(raw).resolve()
    if data not in path.parents and path != data:
        raise HTTPException(status_code=403, detail="evidence path outside data dir")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="unsupported evidence type")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="evidence not found")
    return path


def create_operator_app() -> FastAPI:
    app = FastAPI(title="Operator", version="0.3.0")

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
        """Start work in a background thread so Screen 2 + SSE are live (SPEC §3)."""
        store = get_store()
        run_id = Orchestrator(store).start(goal)

        def _bg() -> None:
            InvoicePipeline(store, build_llm(), _pipeline_cfg(auto_approve=None)).run(
                goal, run_id=run_id
            )

        threading.Thread(target=_bg, daemon=True, name=f"run-{run_id[:8]}").start()
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_view(request: Request, run_id: str) -> HTMLResponse:
        store = get_store()
        working = fold_working_state(store, run_id)
        events = store.list_for_run(run_id)
        report = None
        interpretation = None
        for ev in reversed(events):
            if report is None and ev.type == EventType.REPORT_CREATED:
                report = ev.payload
            if interpretation is None and ev.type == EventType.INTERPRETATION_CREATED:
                interpretation = ev.payload
            if report and interpretation:
                break
        approvals = store.pending_approvals(run_id)
        checklist = _invoice_checklist(store, run_id)
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
                "interpretation": interpretation,
                "approvals": approvals,
                "checklist": checklist,
                "evidence_thumbs": _evidence_thumbs(run_id, report),
                "timeline": replay_run(store, run_id)[-30:],
            },
        )

    @app.get("/runs/{run_id}/evidence")
    def evidence_file(run_id: str, path: str) -> FileResponse:
        _ = run_id
        safe = _safe_evidence_path(path)
        return FileResponse(safe)

    @app.post("/runs/{run_id}/approvals/{approval_id}")
    def decide(run_id: str, approval_id: str, decision: str = Form(...)) -> RedirectResponse:
        store = get_store()
        info = store.decide_approval(approval_id, decision, decided_by="ui")
        store.append(
            run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": approval_id, "decision": decision, "info": info},
        )

        def _bg() -> None:
            InvoicePipeline(store, build_llm(), _pipeline_cfg(auto_approve=None)).resume(run_id)

        threading.Thread(target=_bg, daemon=True, name=f"resume-{run_id[:8]}").start()
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
            for _ in range(600):
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
                if working.state in {"COMPLETE", "FAILED", "ESCALATED", "AWAIT_APPROVAL"}:
                    yield ("data: " + json.dumps({"type": "DONE", "state": working.state}) + "\n\n")
                    if working.state != "AWAIT_APPROVAL":
                        break
                    # Stay subscribed briefly so the approval card can refresh.
                    await asyncio.sleep(0.2)
                    break
                await asyncio.sleep(0.4)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


app = create_operator_app()
