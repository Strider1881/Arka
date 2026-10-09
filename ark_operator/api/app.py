"""FastAPI application for the Operator UI/API (HTMX + SSE)."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from ark_operator.config import get_settings
from ark_operator.domain.enums import outcome_label
from ark_operator.events.replay import fold_working_state, replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.orchestrator import Orchestrator
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_llm
from ark_operator.verify.evidence import collect_run_evidence

TEMPLATES_DIR = Path(__file__).resolve().parent / "ui" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["outcome_label"] = outcome_label


def _data_dir() -> Path:
    """Shared operator data root (CLI + UI). Prefer OPERATOR_DATA_DIR; else DB parent."""
    settings = get_settings()
    raw = (settings.operator_data_dir or "").strip()
    if raw:
        return Path(raw)
    return Path(settings.operator_db_path).resolve().parent


def get_store() -> EventStore:
    """CLI and UI must share one EventStore so approve/status work cross-surface."""
    settings = get_settings()
    path = Path(settings.operator_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _data_dir().mkdir(parents=True, exist_ok=True)
    return EventStore(path)


def _pipeline_cfg(*, auto_approve: bool | None = None) -> PipelineConfig:
    settings = get_settings()
    demo = [s.strip() for s in settings.operator_demo_invoices.split(",") if s.strip()]
    return PipelineConfig(
        portal_base_url=settings.portal_base_url,
        data_dir=_data_dir() / "runs",
        headless=settings.operator_headless,
        auto_approve=auto_approve,
        invoice_filter=demo or None,
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


class _OperatorUIBasicAuthMiddleware(BaseHTTPMiddleware):
    """Optional HTTP Basic Auth when OPERATOR_UI_BASIC_AUTH_* are set.

    ``/health`` stays open for probes. Disabled entirely when user or pass is empty
    so local ``make ui`` / loopback demos stay ungated.
    """

    def __init__(self, app: Any, *, username: str, password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            import base64

            try:
                decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
                user, _, pwd = decoded.partition(":")
            except Exception:
                user, pwd = "", ""
            if secrets.compare_digest(user, self._username) and secrets.compare_digest(
                pwd, self._password
            ):
                return await call_next(request)
        return Response(
            content="Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Operator UI"'},
            media_type="text/plain",
        )


def create_operator_app() -> FastAPI:
    app = FastAPI(title="Operator", version="0.3.0")
    settings = get_settings()
    user = (settings.operator_ui_basic_auth_user or "").strip()
    password = (settings.operator_ui_basic_auth_pass or "").strip()
    if user and password:
        app.add_middleware(_OperatorUIBasicAuthMiddleware, username=user, password=password)

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
        events_for_seq = store.list_for_run(run_id)
        last_seq = events_for_seq[-1].seq if events_for_seq else 0
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
                "last_seq": last_seq,
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
        if not info:
            # Missing / already decided — do not append a fake DECIDED or race a second resume.
            return RedirectResponse(f"/runs/{run_id}", status_code=303)
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
        from ark_operator.runtime.llm_usage import summarize_usage

        store = get_store()
        events = store.list_for_run(run_id)
        timeline = replay_run(store, run_id)
        return templates.TemplateResponse(
            request,
            "details.html",
            {
                "request": request,
                "run_id": run_id,
                "timeline": timeline,
                "usage": summarize_usage(events),
            },
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
