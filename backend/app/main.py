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
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import persistence
from .api.actions import router as actions_router
from .api.comms import router as comms_router
from .api.finance import router as finance_router
from .api.growth import router as growth_router
from .api.router import router
from .connectors import careermind, github
from .core import auth, executive
from .engines import opportunity, publisher
from .engines.evolution import ensure_weights
from .store import STORE, seed

HEARTBEAT_SECONDS = float(os.getenv("TITAN_HEARTBEAT_SECONDS", "5"))
# How often the autonomous growth engine runs a full live-research cycle (24/7).
# Default 4h keeps a free Tavily key (1,000 searches/mo) well within budget:
# 6 cycles/day x 2 searches = ~360/mo, leaving room for on-demand scans.
GROWTH_INTERVAL = float(os.getenv("TITAN_GROWTH_INTERVAL", "14400"))  # 4 hours
_last_growth = 0.0


async def _heartbeat_loop() -> None:
    """Drive autonomous activity on a fixed cadence until cancelled."""
    global _last_growth
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        with contextlib.suppress(Exception):
            executive.heartbeat(STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(publisher.run_due, STORE)
        # Answer any waiting Telegram commands (no-op with no token).
        with contextlib.suppress(Exception):
            from .engines import telegram_bot
            await asyncio.to_thread(telegram_bot.poll_once, STORE)
        # Run the live research engine on its own slow cadence.
        if time.monotonic() - _last_growth >= GROWTH_INTERVAL:
            _last_growth = time.monotonic()
            with contextlib.suppress(Exception):
                from .engines import autonomous
                await asyncio.to_thread(autonomous.growth_cycle, STORE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed(STORE)
    persistence.load(STORE)
    opportunity.discover(STORE)
    ensure_weights(STORE)

    async def _initial_sync() -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(github.refresh, STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(careermind.refresh, STORE)
        # Seed the autonomous research panel so the dashboard has data on open.
        with contextlib.suppress(Exception):
            from .engines import autonomous
            await asyncio.to_thread(autonomous.growth_cycle, STORE)

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

# Paths that never require a login token — the login screen, health checks, the
# voice/assistant UI calls, and the automation endpoints Make.com calls (it has
# no login token). These are low-risk (content generation / append-only logging)
# and the Space URL is private.
_OPEN_PATHS = {
    "/api/login",
    "/api/auth",
    "/health",
    "/api/voice-report",
    "/api/assistant",
    "/api/intelligence",
    "/api/llm/health",
    "/api/doctor",
    "/api/content/daily",
    "/api/intel/news",
    "/api/revenue/log",
    "/api/inbox/auto-reply",
}


@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """Never let browsers cache the HTML shell. Next.js chunks are content-hashed
    (safe to cache forever), but a cached index.html keeps pointing at OLD chunks —
    which is exactly how the HF Space iframe kept showing a stale dashboard."""
    resp = await call_next(request)
    if "text/html" in resp.headers.get("content-type", ""):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if auth.require_auth() and path.startswith("/api") and path not in _OPEN_PATHS:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        # EventSource can't set headers, so the live stream passes its token in
        # the query string instead. Same token, same validation.
        if not token and path == "/api/stream":
            token = request.query_params.get("token", "").strip()
        if not auth.valid_token(token):
            # Automation (Make.com) can authenticate with the webhook secret instead.
            secret = request.headers.get("x-webhook-secret", "")
            expected = os.getenv("TITAN_WEBHOOK_SECRET")
            if not (expected and secret == expected):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


app.include_router(router)
app.include_router(actions_router)
app.include_router(growth_router)
app.include_router(comms_router)
app.include_router(finance_router)


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
