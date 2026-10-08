"""AcmeCorp Procure portal — FastAPI + Jinja2 + SQLite (SPEC §2.1–2.2)."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from company_world.portal.db import get_conn, reset_database
from company_world.portal.faults import VALID_FAULTS, fault_state

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

INVOICE_STATUSES = ("PENDING", "SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED")
APPROVAL_THRESHOLD = 5000.0


def create_app(*, reset_db: bool = True) -> FastAPI:
    """Build the portal ASGI app. reset_db reseeds SQLite on startup."""
    if reset_db:
        reset_database()

    # Re-read env faults on each app create (tests toggle via API / state)
    fault_state.enabled = __import__(
        "company_world.portal.faults", fromlist=["parse_faults_env"]
    ).parse_faults_env()
    raw_n = os.environ.get("SESSION_EXPIRY_N")
    if raw_n:
        fault_state.session_expiry_n = int(raw_n)

    app = FastAPI(title="AcmeCorp Procure", version="0.1.0")
    secret = os.environ.get("PORTAL_SESSION_SECRET", "acme-dev-secret-change-me")

    @app.middleware("http")
    async def fault_middleware(request: Request, call_next: Callable[..., Any]) -> Response:
        # Skip latency/session for admin + static health-ish paths used in tests setup
        path = request.url.path
        if path.startswith("/admin"):
            return await call_next(request)

        fault_state.maybe_latency()

        session = request.session
        sid = session.get("_sid")
        if not sid:
            sid = secrets.token_hex(16)
            session["_sid"] = sid

        if (
            session.get("user_email")
            and fault_state.is_enabled("session_expiry")
            and fault_state.bump_session(sid)
        ):
            session.clear()
            session["_sid"] = secrets.token_hex(16)
            accept = request.headers.get("accept", "")
            if "application/json" in accept and "text/html" not in accept:
                return JSONResponse({"detail": "session expired"}, status_code=401)
            return RedirectResponse("/login?expired=1", status_code=303)

        if request.method == "POST" and fault_state.is_enabled("flaky_500"):
            body = await request.body()

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive)
            key = hashlib.sha256(body + path.encode()).hexdigest()
            # 10% chance once per key; tests can also force via state
            if fault_state.maybe_flaky_500(key):
                return JSONResponse({"detail": "injected flaky_500"}, status_code=500)

        return await call_next(request)

    def current_user(request: Request) -> dict[str, str] | None:
        email = request.session.get("user_email")
        if not email:
            return None
        return {
            "email": email,
            "display_name": request.session.get("display_name", email),
            "role": request.session.get("role", "operator"),
        }

    def require_user(request: Request) -> dict[str, str]:
        user = current_user(request)
        if not user:
            raise _LoginRedirect()
        return user

    class _LoginRedirect(Exception):
        pass

    @app.exception_handler(_LoginRedirect)
    async def _login_redirect_handler(request: Request, exc: _LoginRedirect) -> Response:
        return RedirectResponse("/login", status_code=303)

    def render(
        request: Request,
        name: str,
        ctx: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        base: dict[str, Any] = {
            "request": request,
            "user": current_user(request),
            "ui": fault_state.ui_labels(),
            "faults": fault_state.as_dict(),
            "flash": request.session.pop("flash", None),
            "error": request.session.pop("error", None),
        }
        if ctx:
            base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    def root(request: Request) -> Response:
        if current_user(request):
            return RedirectResponse("/dashboard", status_code=303)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        expired = request.query_params.get("expired")
        return render(
            request,
            "login.html",
            {"expired": bool(expired)},
        )

    @app.post("/login")
    def login(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
    ) -> Response:
        from company_world.portal.passwords import verify_password

        with get_conn() as conn:
            row = conn.execute(
                "SELECT email, password, display_name, role FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        if not row or not verify_password(password, str(row["password"])):
            return render(
                request,
                "login.html",
                {"error_message": "Invalid email or password.", "email": email},
                status_code=401,
            )
        request.session.clear()
        request.session["_sid"] = secrets.token_hex(16)
        request.session["user_email"] = row["email"]
        request.session["display_name"] = row["display_name"]
        request.session["role"] = row["role"]
        fault_state.reset_session_count(request.session["_sid"])
        return RedirectResponse("/dashboard", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        with get_conn() as conn:
            counts = {
                s: conn.execute(
                    "SELECT COUNT(*) AS c FROM invoices WHERE status = ?", (s,)
                ).fetchone()["c"]
                for s in INVOICE_STATUSES
            }
            pending_approvals = conn.execute(
                "SELECT COUNT(*) AS c FROM approval_queue WHERE status = 'PENDING'"
            ).fetchone()["c"]
            vendors = conn.execute("SELECT COUNT(*) AS c FROM vendors").fetchone()["c"]
            pos = conn.execute("SELECT COUNT(*) AS c FROM purchase_orders").fetchone()["c"]
        return render(
            request,
            "dashboard.html",
            {
                "counts": counts,
                "pending_approvals": pending_approvals,
                "vendor_count": vendors,
                "po_count": pos,
            },
        )

    @app.get("/vendors", response_class=HTMLResponse)
    def vendors_list(request: Request) -> HTMLResponse:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, name, status, aliases_json FROM vendors ORDER BY name"
            ).fetchall()
        import json

        vendors = [
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "aliases": json.loads(r["aliases_json"]),
            }
            for r in rows
        ]
        return render(request, "vendors.html", {"vendors": vendors})

    @app.get("/pos", response_class=HTMLResponse)
    def pos_list(request: Request) -> HTMLResponse:
        require_user(request)
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT po.id, po.po_number, po.amount, po.description, po.status,
                       v.name AS vendor_name
                FROM purchase_orders po
                JOIN vendors v ON v.id = po.vendor_id
                ORDER BY po.po_number
                """
            ).fetchall()
        return render(request, "pos.html", {"pos": rows})

    @app.get("/pos/{po_number}", response_class=HTMLResponse)
    def po_detail(request: Request, po_number: str) -> HTMLResponse:
        require_user(request)
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT po.*, v.name AS vendor_name, v.status AS vendor_status
                FROM purchase_orders po
                JOIN vendors v ON v.id = po.vendor_id
                WHERE po.po_number = ?
                """,
                (po_number,),
            ).fetchone()
        if not row:
            return render(request, "not_found.html", {"message": f"PO {po_number} not found"}, 404)
        return render(request, "po_detail.html", {"po": row})

    @app.get("/invoices", response_class=HTMLResponse)
    def invoices_list(request: Request) -> HTMLResponse:
        require_user(request)
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT i.id, i.invoice_number, i.amount, i.invoice_date, i.status,
                       i.attachment_name, v.name AS vendor_name, po.po_number
                FROM invoices i
                JOIN vendors v ON v.id = i.vendor_id
                LEFT JOIN purchase_orders po ON po.id = i.po_id
                ORDER BY i.id DESC
                """
            ).fetchall()
        return render(request, "invoices.html", {"invoices": rows})

    @app.get("/invoices/submit", response_class=HTMLResponse)
    def submit_form(request: Request) -> HTMLResponse:
        require_user(request)
        with get_conn() as conn:
            vendors = conn.execute("SELECT id, name, status FROM vendors ORDER BY name").fetchall()
            pos = conn.execute(
                """
                SELECT po.id, po.po_number, po.amount, v.name AS vendor_name
                FROM purchase_orders po
                JOIN vendors v ON v.id = po.vendor_id
                ORDER BY po.po_number
                """
            ).fetchall()
        return render(
            request,
            "submit_invoice.html",
            {
                "vendors": vendors,
                "pos": pos,
                "today": date.today().isoformat(),
                "banner": request.session.pop("banner", None),
            },
        )

    @app.post("/invoices/submit")
    def submit_invoice(
        request: Request,
        vendor_id: int = Form(...),
        invoice_number: str = Form(...),
        po_id: str = Form(""),
        amount: float = Form(...),
        invoice_date: str = Form(...),
        attachment_name: str = Form(""),
    ) -> Response:
        require_user(request)
        user = require_user(request)
        invoice_number = invoice_number.strip()
        po_id_val: int | None = int(po_id) if po_id.strip() else None

        fingerprint = fault_state.submit_fingerprint(vendor_id, invoice_number, amount, po_id_val)
        if fault_state.check_duplicate_submit(fingerprint):
            request.session["banner"] = {
                "kind": "error",
                "text": "Duplicate submit blocked: an identical invoice was already submitted.",
            }
            return RedirectResponse("/invoices/submit", status_code=303)

        with get_conn() as conn:
            vendor = conn.execute(
                "SELECT id, name, status FROM vendors WHERE id = ?", (vendor_id,)
            ).fetchone()
            if not vendor:
                request.session["error"] = "Unknown vendor."
                return RedirectResponse("/invoices/submit", status_code=303)

            # Status rules for portal acceptance of a submit:
            # - blocked vendor -> still allow record as REJECTED? SPEC: refuse — we mark REJECTED
            # - amount > 5000 -> PENDING_APPROVAL + approval queue
            # - else -> SUBMITTED
            if vendor["status"] == "BLOCKED":
                status = "REJECTED"
            elif amount > APPROVAL_THRESHOLD:
                status = "PENDING_APPROVAL"
            else:
                status = "SUBMITTED"

            try:
                cur = conn.execute(
                    """
                    INSERT INTO invoices (
                        invoice_number, vendor_id, po_id, amount, invoice_date,
                        attachment_name, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_number,
                        vendor_id,
                        po_id_val,
                        amount,
                        invoice_date,
                        attachment_name or None,
                        status,
                    ),
                )
            except Exception as exc:
                request.session["banner"] = {
                    "kind": "error",
                    "text": f"Could not submit invoice: {exc}",
                }
                return RedirectResponse("/invoices/submit", status_code=303)

            invoice_id = int(cur.lastrowid)
            if status == "PENDING_APPROVAL":
                conn.execute(
                    """
                    INSERT INTO approval_queue (invoice_id, requested_by, status)
                    VALUES (?, ?, 'PENDING')
                    """,
                    (invoice_id, user["email"]),
                )

        fault_state.record_submit(fingerprint)
        request.session["flash"] = f"Invoice {invoice_number} recorded as {status}."
        return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)

    @app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
    def invoice_detail(request: Request, invoice_id: int) -> HTMLResponse:
        require_user(request)
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT i.*, v.name AS vendor_name, v.status AS vendor_status,
                       po.po_number, po.amount AS po_amount
                FROM invoices i
                JOIN vendors v ON v.id = i.vendor_id
                LEFT JOIN purchase_orders po ON po.id = i.po_id
                WHERE i.id = ?
                """,
                (invoice_id,),
            ).fetchone()
            approval = None
            if row:
                approval = conn.execute(
                    "SELECT * FROM approval_queue WHERE invoice_id = ?", (invoice_id,)
                ).fetchone()
        if not row:
            return render(
                request, "not_found.html", {"message": f"Invoice {invoice_id} not found"}, 404
            )
        return render(request, "invoice_detail.html", {"invoice": row, "approval": approval})

    @app.get("/approvals", response_class=HTMLResponse)
    def approvals_list(request: Request) -> HTMLResponse:
        require_user(request)
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.status, a.requested_by, a.decided_by, a.decided_at, a.notes,
                       i.id AS invoice_id, i.invoice_number, i.amount, v.name AS vendor_name
                FROM approval_queue a
                JOIN invoices i ON i.id = a.invoice_id
                JOIN vendors v ON v.id = i.vendor_id
                ORDER BY a.id DESC
                """
            ).fetchall()
        return render(request, "approvals.html", {"approvals": rows})

    @app.post("/approvals/{approval_id}/decide")
    def decide_approval(
        request: Request,
        approval_id: int,
        decision: str = Form(...),
        notes: str = Form(""),
    ) -> Response:
        require_user(request)
        user = require_user(request)
        decision = decision.upper().strip()
        if decision not in ("APPROVED", "REJECTED"):
            request.session["error"] = "Decision must be APPROVED or REJECTED."
            return RedirectResponse("/approvals", status_code=303)
        # Policy: manager approves; operator should not approve own — soft check
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?", (approval_id,)
            ).fetchone()
            if not row or row["status"] != "PENDING":
                request.session["error"] = "Approval not found or already decided."
                return RedirectResponse("/approvals", status_code=303)
            if user["role"] != "manager" and user["email"] == row["requested_by"]:
                request.session["error"] = "You cannot approve your own request."
                return RedirectResponse("/approvals", status_code=303)

            conn.execute(
                """
                UPDATE approval_queue
                SET status = ?, decided_by = ?, decided_at = datetime('now'), notes = ?
                WHERE id = ?
                """,
                (decision, user["email"], notes, approval_id),
            )
            inv_status = "APPROVED" if decision == "APPROVED" else "REJECTED"
            conn.execute(
                "UPDATE invoices SET status = ? WHERE id = ?",
                (inv_status, row["invoice_id"]),
            )
        request.session["flash"] = f"Approval #{approval_id} marked {decision}."
        return RedirectResponse("/approvals", status_code=303)

    # --- Admin / API helpers (faults + read-only JSON for verifier later) ---

    def _admin_authorized(request: Request) -> bool:
        """Require manager session OR PORTAL_ADMIN_TOKEN header/query (eval/demo)."""
        user = current_user(request)
        if user and user.get("role") == "manager":
            return True
        token = os.environ.get("PORTAL_ADMIN_TOKEN", "").strip()
        if not token:
            # Demo fallback: operator session also allowed when no token configured,
            # but anonymous is never allowed (closes open /admin/faults).
            return bool(user)

        def _tok_ok(got: str) -> bool:
            if not got or len(got) != len(token):
                return False
            return secrets.compare_digest(got, token)

        hdr = request.headers.get("x-portal-admin-token") or ""
        q = request.query_params.get("admin_token") or ""
        return _tok_ok(hdr) or _tok_ok(q)

    @app.get("/admin/faults")
    def get_faults(request: Request) -> Response:
        if not _admin_authorized(request):
            return JSONResponse({"detail": "admin auth required"}, status_code=401)
        return fault_state.as_dict()

    @app.post("/admin/faults")
    async def set_faults(request: Request) -> Response:
        if not _admin_authorized(request):
            return JSONResponse({"detail": "admin auth required"}, status_code=401)
        payload = await request.json()
        faults = payload.get("faults", [])
        if isinstance(faults, str):
            faults = [f.strip() for f in faults.split(",") if f.strip()]
        unknown = [f for f in faults if f not in VALID_FAULTS]
        enabled = fault_state.set_faults(faults)
        if "session_expiry_n" in payload:
            fault_state.session_expiry_n = int(payload["session_expiry_n"])
        if "flaky_force" in payload:
            fault_state.flaky_test_force = bool(payload["flaky_force"])
        if "rng_seed" in payload:
            fault_state.rng_seed = int(payload["rng_seed"])
        if payload.get("reset_counters", True):
            fault_state.session_request_counts.clear()
            fault_state.flaky_fired.clear()
            fault_state.submitted_fingerprints.clear()
        return {"enabled": sorted(enabled), "unknown": unknown, **fault_state.as_dict()}

    @app.post("/admin/reset")
    def admin_reset(request: Request) -> Response:
        if not _admin_authorized(request):
            return JSONResponse({"detail": "admin auth required"}, status_code=401)
        reset_database()
        fault_state.session_request_counts.clear()
        fault_state.flaky_fired.clear()
        fault_state.submitted_fingerprints.clear()
        return {"status": "ok"}

    @app.get("/api/vendors")
    def api_vendors(request: Request) -> list[dict[str, Any]]:
        require_user(request)
        import json

        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM vendors ORDER BY name").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "aliases": json.loads(r["aliases_json"]),
            }
            for r in rows
        ]

    @app.get("/api/pos")
    def api_pos(request: Request) -> list[dict[str, Any]]:
        require_user(request)
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT po.po_number, po.amount, po.description, po.status, v.name AS vendor
                FROM purchase_orders po JOIN vendors v ON v.id = po.vendor_id
                ORDER BY po.po_number
                """
            ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/invoices")
    def api_invoices(request: Request) -> list[dict[str, Any]]:
        require_user(request)
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT i.invoice_number, i.amount, i.invoice_date, i.status, i.attachment_name,
                       v.name AS vendor, po.po_number
                FROM invoices i
                JOIN vendors v ON v.id = i.vendor_id
                LEFT JOIN purchase_orders po ON po.id = i.po_id
                ORDER BY i.id
                """
            ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "acmecorp-procure"}

    # SessionMiddleware last => outermost so request.session works in fault middleware
    app.add_middleware(SessionMiddleware, secret_key=secret, session_cookie="acme_session")
    return app


def main() -> None:
    """CLI entry for `make portal`."""
    import uvicorn

    host = os.environ.get("PORTAL_HOST", "127.0.0.1")
    port = int(os.environ.get("PORTAL_PORT", "8765"))
    uvicorn.run(
        "company_world.portal.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
