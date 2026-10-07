"""HTTP routes for durable approval decisions.

STUB: P6/P9.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/")
def list_approvals() -> dict[str, object]:
    """List pending approvals. STUB."""
    return {"approvals": [], "note": "STUB"}
