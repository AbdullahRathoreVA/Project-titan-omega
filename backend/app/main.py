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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import router
from .connectors import github
from .core import executive
from .engines import opportunity, publisher
from .store import STORE, seed

HEARTBEAT_SECONDS = float(os.getenv("TITAN_HEARTBEAT_SECONDS", "5"))


async def _heartbeat_loop() -> None:
    """Drive autonomous activity on a fixed cadence until cancelled.

    Each tick advances agent activity and auto-publishes any scheduled posts whose
    time has come — so the empire keeps working and posting around the clock.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        with contextlib.suppress(Exception):
            executive.heartbeat(STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(publisher.run_due, STORE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cold start: stand up the org and surface opportunities (instant), then sync
    # live connectors in the background so boot isn't blocked on the network.
    seed(STORE)
    opportunity.discover(STORE)

    async def _initial_sync() -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(github.refresh, STORE)

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
    version="0.1.0",
    lifespan=lifespan,
)

# The dashboard runs on a different origin in dev; allow it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("TITAN_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "online", "service": "titan-omega-core", "agents": len(STORE.agents)}


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": "Project Titan Omega",
        "tagline": "Autonomous Founder Empire Operating System",
        "docs": "/docs",
        "api": "/api",
    }
