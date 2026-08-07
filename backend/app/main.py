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

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import persistence
from .core import envfile

# Before anything reads configuration. A value already in the environment (on
# Hugging Face, the Space secrets) always wins over the file.
_ENV_LOADED = envfile.autoload()
from .api.actions import router as actions_router
from .api.comms import router as comms_router
from .api.finance import router as finance_router
from .api.growth import router as growth_router
from .api.router import router
from .api.tts import router as tts_router
from .connectors import careermind, github
from .core import auth, demo_data, executive, traffic
from .engines import client_watch, opportunity, publisher
from .engines.evolution import ensure_weights
from .store import STORE, seed

HEARTBEAT_SECONDS = float(os.getenv("TITAN_HEARTBEAT_SECONDS", "5"))
# How often the autonomous growth engine runs a full live-research cycle (24/7).
# Default 4h keeps a free Tavily key (1,000 searches/mo) well within budget:
# 6 cycles/day x 2 searches = ~360/mo, leaving room for on-demand scans.
GROWTH_INTERVAL = float(os.getenv("TITAN_GROWTH_INTERVAL", "14400"))  # 4 hours
_last_growth = 0.0
# Client site monitoring cadence. 30 min between ticks; each tick checks at most
# 3 clients whose own 6-hour window has elapsed, so no site is hit often.
WATCH_INTERVAL = float(os.getenv("TITAN_WATCH_INTERVAL", "1800"))
_last_watch = 0.0


async def _heartbeat_loop() -> None:
    """Drive autonomous activity on a fixed cadence until cancelled."""
    global _last_growth, _last_watch
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
        # Autonomous client monitoring. Runs with nobody logged in — this is
        # what makes the service continuous rather than on-demand.
        if time.monotonic() - _last_watch >= WATCH_INTERVAL:
            _last_watch = time.monotonic()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(client_watch.cycle)
            # Titan audits its own site with the engine it sells. Rides the
            # existing client-watch tick rather than adding a timer: self_seo
            # keeps its own 6-hour interval internally, so calling it more
            # often than that is a cheap no-op.
            with contextlib.suppress(Exception):
                from .engines import self_seo
                await asyncio.to_thread(self_seo.cycle)
            # Per-client news watch. Keeps its own 3-hour interval and
            # round-robins a few clients per tick, so a large portfolio never
            # stalls the heartbeat.
            with contextlib.suppress(Exception):
                from .engines import client_news
                await asyncio.to_thread(client_news.cycle)

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
    # Register the external-capability adapters. Idempotent, no network, no
    # imports of optional packages — a tool that is not configured simply
    # reports what it needs.
    from .engines import adapters
    adapters.register_all()

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
    "/api/demo/enter",
    "/api/session",
    "/health",
    "/api/voice-report",
    "/api/assistant",
    "/api/intelligence",
    "/api/llm/health",
    "/api/tts/health",
    "/api/doctor",
    "/api/content/daily",
    "/api/intel/news",
    "/api/inbox/auto-reply",
    # Public product surface. Pricing must be readable and signup reachable
    # without a founder token, or nobody can ever become a customer — the
    # whole point of Part 5B.
    "/api/plans",
    "/api/signup",
    "/api/account/login",
    # Titan's own audit score and product schema are marketing assets — they
    # are meant to be read by strangers and by crawlers.
    "/api/self-seo",
    "/api/structured-data",
    # NOTE: the client portal is handled by _OPEN_PREFIXES below, not here.
    # Listing each path individually meant every new client endpoint silently
    # 401'd until someone remembered to register it — /client/social and
    # /client/report.pdf both did exactly that.
    # NOTE: /api/revenue/log is deliberately NOT open. It writes to the real
    # money ledger, and this deployment is publicly reachable (demo button), so
    # it now requires the founder token or the X-Webhook-Secret header. Make.com
    # must send:  X-Webhook-Secret: <TITAN_WEBHOOK_SECRET>
}


# Every /api/client/* route carries its OWN credential (X-Client-Token), is
# scoped to exactly one business, and fails closed on an unrecognised token.
# So the whole prefix bypasses the FOUNDER token guard without weakening it —
# admin client management stays behind the founder token.
#
# A prefix rather than a list of exact paths: listing them individually meant
# every new client endpoint silently 401'd until someone remembered to register
# it, which is exactly what happened to /client/social and /client/report.pdf.
#
# /api/account and /api/checkout/* carry their OWN credential (X-Account-Token)
# and are scoped to one subscriber, exactly like the client portal above. They
# bypass the FOUNDER guard without weakening it: an unknown account token
# resolves to nothing and the endpoint 401s.
_OPEN_PREFIXES = ("/api/client/", "/api/account", "/api/checkout/")


def _static_page(name: str) -> FileResponse:
    import os as _os
    page = _os.path.join(_os.path.dirname(__file__), "static", name)
    if not _os.path.exists(page):
        raise HTTPException(status_code=404, detail=f"{name} not installed")
    return FileResponse(page, media_type="text/html")


@app.get("/robots.txt", include_in_schema=False)
def robots():
    """Titan's own robots.txt.

    NOTE: Cloudflare serves a managed AI-content-signals robots.txt at the zone
    level, which takes precedence at the edge and does NOT declare a sitemap.
    If this file is not what titanomega-ai.com returns, disable the managed
    robots.txt in the Cloudflare dashboard so this one is served instead.
    """
    from .engines import self_seo
    return Response(content=self_seo.robots_txt(), media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Titan's audit reports a missing sitemap as a finding on client sites.
    Shipping without one was indefensible."""
    from .engines import self_seo
    return Response(content=self_seo.sitemap_xml(),
                    media_type="application/xml")


@app.get("/privacy", include_in_schema=False)
def privacy_page():
    """Exists because Titan's own audit flagged its absence as legal-critical
    against titanomega-ai.com — the same finding it charges clients to fix.
    Signup now collects email addresses and the target market is the EU."""
    return _static_page("privacy.html")


@app.get("/pricing", include_in_schema=False)
def pricing_page_with_schema():
    """Pricing, with the product JSON-LD injected SERVER-SIDE.

    The page originally fetched /api/structured-data and appended a script tag
    from JavaScript. Google executes JS, but most AI answer-engine crawlers do
    not — and Titan's own audit tells clients that schema is how those engines
    decide what to quote. Schema that only exists after hydration is schema
    those crawlers never see, so Titan was failing its own advice.

    Injected at request time rather than baked into the file so the marked-up
    prices are generated from the live plan table and cannot drift from what is
    actually charged.
    """
    import json as _json
    import os as _os

    from .engines import self_seo

    page = _os.path.join(_os.path.dirname(__file__), "static", "pricing.html")
    if not _os.path.exists(page):
        raise HTTPException(status_code=404, detail="pricing.html not installed")
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    ld = _json.dumps(self_seo.structured_data(), ensure_ascii=False)
    # Escaping "</" prevents a stray closing tag inside the JSON from ending the
    # script element early, which would break the page and the markup with it.
    ld = ld.replace("</", "<\\/")
    tag = f'<script type="application/ld+json">{ld}</script>\n</head>'
    return Response(content=html.replace("</head>", tag, 1),
                    media_type="text/html")


@app.get("/portal", include_in_schema=False)
def client_portal():
    """The screen a client logs into. Static, no build step."""
    return _static_page("client.html")


@app.get("/clients", include_in_schema=False)
def admin_console():
    """Abdullah's console: every business he manages, on one screen.

    The page itself is public HTML — it holds no data. Everything it renders
    comes from /api/admin/* which stays behind the founder token, so serving
    the shell openly leaks nothing.
    """
    return _static_page("admin.html")


@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """Never let browsers cache the HTML shell. Next.js chunks are content-hashed
    (safe to cache forever), but a cached index.html keeps pointing at OLD chunks —
    which is exactly how the HF Space iframe kept showing a stale dashboard."""
    resp = await call_next(request)
    if "text/html" in resp.headers.get("content-type", ""):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


_ASSET_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico",
                   ".webp", ".woff", ".woff2", ".map", ".json", ".txt", ".xml",
                   ".webmanifest")


@app.middleware("http")
async def count_visitors(request: Request, call_next):
    """Count HTML page loads so the founder can see who opened the site.

    Only page loads: counting assets and API calls would turn a single visit
    into thirty and make the number worthless. See core/traffic.py for why no
    IP is stored.
    """
    resp = await call_next(request)
    try:
        path = request.url.path
        if (request.method == "GET" and resp.status_code < 400
                and not path.startswith(("/api/", "/_next/"))
                and not path.endswith(_ASSET_SUFFIXES)):
            client_host = request.client.host if request.client else ""
            traffic.record(
                path=path,
                # Behind the Cloudflare Worker the socket peer is Cloudflare,
                # not the visitor — the real address is in CF-Connecting-IP.
                ip=(request.headers.get("cf-connecting-ip")
                    or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                    or client_host),
                user_agent=request.headers.get("user-agent", ""),
                referrer=request.headers.get("referer", ""),
            )
    except Exception:
        pass
    return resp


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if (auth.require_auth() and path.startswith("/api")
            and path not in _OPEN_PATHS
            and not path.startswith(_OPEN_PREFIXES)):
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        # EventSource can't set headers, so the live stream passes its token in
        # the query string instead. Same token, same validation.
        if not token and path == "/api/stream":
            token = request.query_params.get("token", "").strip()
        if not auth.valid_token(token):
            # --- public read-only demo session ---------------------------
            # A guest token unlocks GET only, and every endpoint holding real
            # business data is answered with demo-safe sample content.
            if auth.valid_guest_token(token):
                if request.method not in ("GET", "HEAD"):
                    return JSONResponse(
                        {"detail": "Read-only demo — actions are disabled.", "guest": True},
                        status_code=403,
                    )
                try:
                    limit = int(request.query_params.get("limit", 50))
                except ValueError:
                    limit = 50
                payload = demo_data.guest_payload(path, limit)
                if payload is not None:
                    return JSONResponse(payload)
                if demo_data.is_sensitive(path):
                    # Any private path without an explicit sample is refused
                    # outright — fail closed, never leak.
                    return JSONResponse({"detail": "Hidden in demo", "guest": True}, status_code=403)
                return await call_next(request)

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
app.include_router(tts_router)


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
