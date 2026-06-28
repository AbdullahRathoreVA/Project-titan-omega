"""Titan Omega backend entrypoint.

Boots the Executive Intelligence Core, seeds the Digital Employee Network, runs
the Global Opportunity Engine once, and starts a background heartbeat so the
empire keeps working with no operator input.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import persistence
from .api.router import router
from .connectors import careermind, github
from .core import auth, executive
from .engines import opportunity, publisher
from .engines.evolution import ensure_weights
from .store import STORE, seed

HEARTBEAT_SECONDS = float(os.getenv("TITAN_HEARTBEAT_SECONDS", "5"))


async def _heartbeat_loop() -> None:
    """Drive autonomous activity on a fixed cadence until cancelled."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        with contextlib.suppress(Exception):
            executive.heartbeat(STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(publisher.run_due, STORE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed(STORE)
    # Restore real earnings (metrics + revenue ledger) saved from a prior run.
    persistence.load(STORE)
    opportunity.discover(STORE)
    ensure_weights(STORE)

    async def _initial_sync() -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(github.refresh, STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(careermind.refresh, STORE)

    sync_task = asyncio.create_task(_initial_sync())
    task = asyncio.create_task(_heartbeat_loop())
    try:
        yield
    finally:
        for t in (task, sync_task):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t


app = FastAPI(
    title="Project Titan Omega",
    description="Autonomous Founder Empire Operating System — Executive Intelligence Core API.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("TITAN_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths that never require an auth token — login screen, health checks,
# and the Urdu voice + Ask Titan assistant (called directly from the UI
# without a Bearer token in the request).
_OPEN_PATHS = {
    "/api/login",
    "/api/auth",
    "/health",
    "/api/voice-report",
    "/api/assistant",
    "/api/intelligence",
}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if auth.require_auth() and path.startswith("/api") and path not in _OPEN_PATHS:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not auth.valid_token(token):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


app.include_router(router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "online", "service": "titan-omega-core", "agents": len(STORE.agents)}


_FRONTEND_OUT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "out")
if os.path.isdir(_FRONTEND_OUT):
    app.mount("/", StaticFiles(directory=_FRONTEND_OUT, html=True), name="dashboard")
else:

    @app.get("/", tags=["system"])
    def root() -> dict:
        return {
            "name": "Project Titan Omega",
            "tagline": "Autonomous Founder Empire Operating System",
            "docs": "/docs",
            "api": "/api",
        }
