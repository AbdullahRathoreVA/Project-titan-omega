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
from .api.voice import router as voice_router
from .connectors import careermind, github
from .core import auth, demo_data, executive, traffic
from .engines import client_watch, opportunity, publisher
from .engines.evolution import ensure_weights
from .store import STORE, seed

HEARTBEAT_SECONDS = float(os.getenv("TITAN_HEARTBEAT_SECONDS", "5"))

# The background loop is the product's whole "24/7" claim, so it is ON by
# default and only the test suite turns it off. Tests exercise every cycle by
# calling it directly; letting the loop also run inside ~100 TestClient
# instantiations made the suite take SIX AND A HALF HOURS instead of two
# minutes (each app start fired a full SQLite backup, an embedding-model
# download and every scheduled cycle — see the interval note below).
HEARTBEAT_ENABLED = os.getenv("TITAN_HEARTBEAT_ENABLED", "1").strip() not in (
    "0", "false", "no", "")
# How often the autonomous growth engine runs a full live-research cycle (24/7).
# Default 4h keeps a free Tavily key (1,000 searches/mo) well within budget:
# 6 cycles/day x 2 searches = ~360/mo, leaving room for on-demand scans.
GROWTH_INTERVAL = float(os.getenv("TITAN_GROWTH_INTERVAL", "14400"))  # 4 hours
# Client site monitoring cadence. 30 min between ticks; each tick checks at most
# 3 clients whose own 6-hour window has elapsed, so no site is hit often.
WATCH_INTERVAL = float(os.getenv("TITAN_WATCH_INTERVAL", "1800"))
# Six hours. Frequent enough that a rebuild loses at most one window of work,
# rare enough that snapshotting is never a meaningful share of what this
# container is doing.
BACKUP_INTERVAL = float(os.getenv("TITAN_BACKUP_INTERVAL", str(6 * 3600)))
# Re-measure every ACTIVE self-improvement and roll back any that got worse.
# Six hours: a regression should not sit in production for a day, and the
# check re-measures each active parameter, so it is not free.
IMPROVE_INTERVAL = float(os.getenv("TITAN_IMPROVE_INTERVAL", str(6 * 3600)))

# Seeded to NOW, not to 0.0. `time.monotonic()` is time since system boot on
# every platform Titan runs on, so `monotonic() - 0.0 >= INTERVAL` is TRUE on
# the very first tick — every scheduled cycle fired immediately at startup.
# In production that is a thundering herd on boot: a full SQLite backup, an
# embedding-model download and every 24/7 cycle, all before the app has served
# a request. Seeding to now means the first run of each happens one real
# interval after boot, which is what the intervals were written to mean.
_last_growth = time.monotonic()
_last_watch = time.monotonic()
_last_backup = time.monotonic()
_last_improve = time.monotonic()


async def _heartbeat_loop() -> None:
    """Drive autonomous activity on a fixed cadence until cancelled."""
    if not HEARTBEAT_ENABLED:
        return
    global _last_growth, _last_watch, _last_improve
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        with contextlib.suppress(Exception):
            executive.heartbeat(STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(publisher.run_due, STORE)
        # The durable queue. Bounded per tick so a deep backlog can never
        # monopolise the heartbeat, and it is what takes crawls off the
        # request path — a container recycled mid-audit retries instead of
        # losing the work silently.
        with contextlib.suppress(Exception):
            from .core import queue
            await asyncio.to_thread(queue.drain, 3)
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

            # Gives the audit, knowledge and watch engines real sites to work
            # on instead of spinning against an empty client list. Keeps its
            # own 6-hour interval, so this is a no-op the rest of the time.
            with contextlib.suppress(Exception):
                from .engines import demo_workspace
                await asyncio.to_thread(demo_workspace.cycle)

            # Per-client news watch. Keeps its own 3-hour interval and
            # round-robins a few clients per tick, so a large portfolio never
            # stalls the heartbeat.
            with contextlib.suppress(Exception):
                from .engines import client_news
                await asyncio.to_thread(client_news.cycle)

            # The 24/7 half of the fix loop. Enqueues re-audits for every
            # connected site; it never applies anything. Keeps its own 6-hour
            # interval, so this is a cheap no-op the rest of the time.
            with contextlib.suppress(Exception):
                from .engines import fix_cycle
                await asyncio.to_thread(fix_cycle.cycle)

            # Embed anything indexed while the model was still downloading.
            # THIS WAS THE BUG: knowledge.backfill() existed, was tested, and
            # was exposed as a manual endpoint that nothing ever called — so
            # in production it never ran. Pages ingested in the first minutes
            # after a rebuild kept no vectors and were never re-embedded, and
            # that client stayed keyword-only forever. On a free Space that
            # rebuilds often, that was most clients, and it is the likeliest
            # cause of the measured 2/4 retrieval score.
            #
            # On the heartbeat rather than the queue deliberately: it is
            # idempotent, bounded by MAX_PASSAGES, and a no-op when nothing is
            # pending — durability buys nothing here and a job row per tick
            # would be noise.
            with contextlib.suppress(Exception):
                from .core import knowledge
                await asyncio.to_thread(knowledge.backfill)

            with contextlib.suppress(Exception):
                from .core import queue
                await asyncio.to_thread(queue.trim)

            # A scheduled, self-verifying backup. Keeps its own interval.
            # Titan holds the only copy of the previous value of pages it has
            # changed on customers' live websites; losing that store loses the
            # ability to undo those changes.
            if time.monotonic() - _last_backup >= BACKUP_INTERVAL:
                globals()["_last_backup"] = time.monotonic()
                with contextlib.suppress(Exception):
                    from .core import backup
                    made = await asyncio.to_thread(backup.create, "scheduled")
                    # Only a backup that VERIFIED is worth uploading. backup
                    # proves itself by restoring into a scratch database and
                    # counting rows; shipping one that failed that check would
                    # replace a good snapshot with a broken one.
                    #
                    # The path lives at manifest["file"] -- there is no
                    # top-level "path" key, and reading one returns None, which
                    # is falsy, so the upload would simply never have happened
                    # and the absence would have looked exactly like "nothing
                    # to push".
                    manifest = (made or {}).get("manifest") or {}
                    if (made or {}).get("ok") and manifest.get("verified") \
                            and manifest.get("file"):
                        from .core import remote_state as _remote
                        if _remote.configured():
                            await asyncio.to_thread(
                                _remote.push, manifest["file"],
                                note="scheduled")

            # The self-improvement loop's automatic half. THIS WAS THE SAME BUG
            # AS knowledge.backfill(): improve.check_active() re-measures every
            # ACTIVE change and rolls back any that got worse, it is tested, it
            # is mutation-guarded, and NOTHING IN PRODUCTION EVER CALLED IT. So
            # "auto-rollback on regression" was true of the function and false
            # of the deployment, and an approved change that made Titan worse
            # stayed live until somebody clicked an endpoint by hand.
            #
            # Safe to automate precisely because it is the only direction that
            # is safe: it never proposes, never approves and never activates.
            # It can only move a value BACK to one a human already approved.
            if time.monotonic() - _last_improve >= IMPROVE_INTERVAL:
                globals()["_last_improve"] = time.monotonic()
                with contextlib.suppress(Exception):
                    from .core import improve
                    await asyncio.to_thread(improve.check_active)

        # Run the live research engine on its own slow cadence.
        if time.monotonic() - _last_growth >= GROWTH_INTERVAL:
            _last_growth = time.monotonic()
            with contextlib.suppress(Exception):
                from .engines import autonomous
                await asyncio.to_thread(autonomous.growth_cycle, STORE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FIRST, before anything is loaded or served. A deployment that enforces
    # authentication and has no usable TITAN_SECRET must not answer a single
    # request: it would be signing founder sessions, and encrypting the
    # WordPress credential vault, with a key printed in the public repository.
    # Deliberately NOT wrapped in contextlib.suppress — this one is meant to
    # stop the boot. See core/appsecret.py.
    from .core import appsecret as _appsecret
    _appsecret.verify_at_startup()

    # BEFORE anything reads the database. A free Space wipes /tmp on every
    # rebuild, so on a fresh container the state file is simply absent and the
    # latest verified snapshot is pulled back from a free private Dataset repo.
    # `remote_state.pull` REFUSES if a state file already exists, so this can
    # only ever restore towards an empty database -- overwriting a live one
    # with an older snapshot is the direction that loses data.
    # The result used to be discarded. A restore that failed — expired token,
    # renamed repo, Hub outage — wiped every account and said nothing, and the
    # symptom was identical to a healthy first boot with no snapshot yet.
    with contextlib.suppress(Exception):
        from .core import remote_state as _remote
        if not _remote.configured():
            _remote.record_restore("not_configured", {"missing": _remote.missing()})
        elif os.path.exists(persistence.STATE_FILE):
            _remote.record_restore("skipped_local_state_exists")
        else:
            result = _remote.pull(persistence.STATE_FILE)
            _remote.record_restore(
                "restored" if result.get("ok") else "failed",
                {"bytes": result.get("bytes"),
                 "reason": result.get("reason")} if not result.get("ok")
                else {"bytes": result.get("bytes")})

    seed(STORE)
    persistence.load(STORE)
    # Seed the founder account from the environment, and with it retire the
    # plaintext comparison in core/auth.py. Idempotent, and it never raises: a
    # deployment that has not set TITAN_FOUNDER_EMAIL keeps the old gate and
    # says so on /api/auth, rather than refusing to serve. Unlike the secret
    # check above, being unconfigured here is a downgrade, not a danger.
    with contextlib.suppress(Exception):
        from .core import identity as _identity
        _identity.ensure_founder()
    opportunity.discover(STORE)
    ensure_weights(STORE)
    # Register the external-capability adapters. Idempotent, no network, no
    # imports of optional packages — a tool that is not configured simply
    # reports what it needs.
    from .engines import adapters
    adapters.register_all()
    # Re-apply approved parameter overrides to the live modules. Without this
    # an approved, activated improvement silently reverts on the next rebuild
    # and nobody would know why the numbers moved back — the same shape as
    # knowledge.backfill(), which existed, was tested, was exposed as an
    # endpoint, and had zero callers.
    with contextlib.suppress(Exception):
        from .core import params as _params
        _params.apply_stored()
    # Bind job kinds to their handlers BEFORE the heartbeat drains anything,
    # so work already sitting in the queue from a previous container is picked
    # up on this boot rather than parked as unhandled.
    with contextlib.suppress(Exception):
        from .engines import fix_cycle
        fix_cycle.register_handlers()

    async def _initial_sync() -> None:
        # Same gate as the heartbeat: these are three network round trips
        # (GitHub, CareerMind, a live web-research cycle) fired on every app
        # start, which in the test suite means on every TestClient.
        if not HEARTBEAT_ENABLED:
            return
        with contextlib.suppress(Exception):
            await asyncio.to_thread(github.refresh, STORE)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(careermind.refresh, STORE)
        # Seed the autonomous research panel so the dashboard has data on open.
        with contextlib.suppress(Exception):
            from .engines import autonomous
            await asyncio.to_thread(autonomous.growth_cycle, STORE)
        # One backup shortly after boot, then every BACKUP_INTERVAL.
        #
        # Seeding the interval trackers to "now" fixed the boot stampede, but
        # it also meant the first backup would be six hours after start — and
        # a free Space frequently rebuilds sooner than that, so in practice a
        # backup might never be taken at all. It measured ~20ms, so taking one
        # here costs nothing and is exactly the case backups exist for: an
        # ephemeral disk that can be wiped at any moment.
        with contextlib.suppress(Exception):
            from .core import backup
            await asyncio.to_thread(backup.create, "boot")

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
    # Opens the CUSTOMER product for a stranger, with no token. Public on
    # purpose: it is the demo. It can only ever reach a business Titan owns —
    # see demo_workspace.showcase(), which returns None rather than falling
    # back to a real client.
    "/api/demo/portal",
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
# /api/org carries its own credential too - an identity session resolved
# through core/identity.py, scoped to one organisation by membership and
# failing closed on an unrecognised token. Same contract as the three
# above, so it bypasses the FOUNDER guard without weakening it.
_OPEN_PREFIXES = ("/api/client/", "/api/account", "/api/checkout/",
                  "/api/org")


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


@app.get("/compliance/{code}", include_in_schema=False)
def compliance_landing(code: str):
    """Per-jurisdiction legal requirements, server-rendered.

    Server-rendered on purpose: the dashboard is a client-rendered SPA, and
    Titan's own audit already caught its homepage serving an empty shell to
    crawlers. A page written to be found must be readable with JavaScript off.
    """
    from .engines import landing
    page = landing.compliance_page(code)
    if not page:
        raise HTTPException(status_code=404, detail="Unknown jurisdiction")
    return Response(content=page, media_type="text/html")


@app.get("/seo/{vertical}", include_in_schema=False)
def vertical_landing(vertical: str):
    """Per-vertical ranking factors, server-rendered. Same reasoning."""
    from .engines import landing
    page = landing.vertical_page(vertical)
    if not page:
        raise HTTPException(status_code=404, detail="Unknown business type")
    return Response(content=page, media_type="text/html")


@app.get("/join", include_in_schema=False)
def join_page():
    """Signup → pick a plan → add a business → first audit → PDF, on one screen.

    Static for the same reason /pricing is: this is where a stranger decides
    whether Titan is worth the trouble, and it must render before a 175 kB
    dashboard bundle would have finished downloading. It holds no logic — every
    number and limit comes from the API that enforces them.
    """
    return _static_page("join.html")


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
                # Cloudflare adds this on every proxied request at no cost and
                # with no IP database. Country only, deliberately.
                country=request.headers.get("cf-ipcountry", ""),
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


# Registered LAST, and that is load-bearing. Starlette's `add_middleware`
# inserts at the FRONT of the list, so the last one registered is the
# OUTERMOST and runs first. Declared any earlier in this file, this would sit
# inside `auth_guard` and every 401/403 — the requests you most want a record
# of — would never be logged at all.
@app.middleware("http")
async def request_log(request: Request, call_next):
    """One structured line per request, with an id that follows the work.

    The id is returned in `X-Request-Id`, so a customer reporting a problem can
    quote a number that finds the exact request. An inbound `X-Request-Id` is
    honoured (truncated) so a trace survives a proxy hop.
    """
    from .core import obs

    rid = (request.headers.get("x-request-id") or "").strip()[:32] or obs.new_request_id()
    obs.bind(request_id=rid)
    started = time.monotonic()
    path = request.url.path
    try:
        resp = await call_next(request)
    except Exception as exc:
        obs.error("http.request", method=request.method, path=path,
                  duration_ms=round((time.monotonic() - started) * 1000, 1),
                  error=f"{type(exc).__name__}: {str(exc)[:200]}")
        raise
    ms = round((time.monotonic() - started) * 1000, 1)
    # Assets are most of the traffic and none of the signal. Logging every
    # chunk would bury the API calls that matter.
    if not path.endswith(_ASSET_SUFFIXES) and not path.startswith("/_next/"):
        obs.log("http.request",
                "error" if resp.status_code >= 500
                else "warn" if resp.status_code >= 400 else "info",
                method=request.method, path=path,
                status=resp.status_code, duration_ms=ms)
    resp.headers["X-Request-Id"] = rid
    return resp


app.include_router(router)
app.include_router(actions_router)
app.include_router(growth_router)
app.include_router(comms_router)
app.include_router(finance_router)
app.include_router(tts_router)
app.include_router(voice_router)


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
