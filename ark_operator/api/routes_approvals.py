"""HTTP routes for durable approval decisions."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("/")
def list_approvals() -> dict[str, object]:
    return {"approvals": [], "note": "Use HTML approval forms on /runs/{id}"}
