"""
PlacementPilot — FastAPI application entry point.

Phase 0 / Phase 1: health-check only.
Ingestion endpoints (POST /ingest/resume, POST /ingest/jd) will be wired
in Phase 6 once the full pipeline (embedding, retrieval, generation) is ready.
"""

from fastapi import FastAPI

app = FastAPI(
    title="PlacementPilot API",
    description=(
        "RAG-based resume-to-JD gap analysis. "
        "Answers only from retrieved context — refuses when it doesn't know."
    ),
    version="0.1.0",
)


@app.get("/health", tags=["meta"])
def health_check() -> dict:
    """Liveness check. Returns 200 when the service is up."""
    return {"status": "ok", "service": "placementpilot-backend"}
