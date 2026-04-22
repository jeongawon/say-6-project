"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import triage, orders, encounters, reports, ws
from app.config import APP_HOST, APP_PORT

app = FastAPI(
    title="Emergency Multimodal Orchestrator — Backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────
app.include_router(triage.router, prefix="/triage", tags=["triage"])
app.include_router(orders.router, prefix="/orders", tags=["orders"])
app.include_router(encounters.router, prefix="/encounters", tags=["encounters"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(ws.router, tags=["websocket"])


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=True)
