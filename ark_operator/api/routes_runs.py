"""HTTP routes for starting and inspecting runs."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/")
def list_runs() -> dict[str, object]:
    """List runs. Prefer HTML UI routes in app.py for the demo path."""
    return {"runs": [], "note": "Use GET / and POST /runs HTML handoff"}
