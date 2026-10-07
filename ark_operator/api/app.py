"""FastAPI application entrypoint for the Operator UI/API.

STUB: full routes and templates in P9; minimal app shell for P0 importability.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Operator",
    description="STUB: UI and API land in later phases (P9).",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for smoke tests."""
    return {"status": "ok", "phase": "P0"}
