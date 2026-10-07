"""HTTP routes for starting and inspecting runs.

STUB: P9.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/")
def list_runs() -> dict[str, object]:
    """List runs. STUB."""
    return {"runs": [], "note": "STUB"}
