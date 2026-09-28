"""Titan Omega backend entry point.

Boots the executive core, seeds the agent network, runs the opportunity engine
once, and starts the background heartbeat that keeps everything running with
no operator input.

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

# Before anything reads configuration. A value already in the environment (the
# Space secrets, on Hugging Face) always wins over the file.
_ENV_LOADED = envfile.autoload()
from .api.actions import router as actions_router
from .api.comms import router as comms_router
from .api.finance import router as finance_router
from .api.growth import router as growth_router
from .api.mine import router as mine_router
from .api.router import router
from .api.tts import router as tts_router
from .api.voice import router as voice_router
from .connectors import careermind, github
from .core import auth, demo_data, executive, traffic
from .engines import client_watch, opportunity, publisher
from .engines.evolution import ensure_weights
from .store import STORE, seed

HEARTBEAT_SECONDS = float(os.getenv("TITAN_HEARTBEAT_SECONDS", "5"))

# The background loop is on by default; only the test suite turns it off. Tests
# call each cycle directly, and letting the loop also run inside every
# TestClient (each start firing a backup, an embedding-model download and every
# scheduled cycle) makes the suite take hours instead of minutes.
HEARTBEAT_ENABLED = os.getenv("TITAN_HEARTBEAT_ENABLED", "1").strip() not in (
    "0", "false", "no", "")
# How often the autonomous growth engine runs a full live-research cycle.
# The 4h default keeps a free Tavily key (1,000 searches/month) well within
# budget: 6 cycles/day x 2 searches = ~360/month, leaving room for manual scans.
GROWTH_INTERVAL = float(os.getenv("TITAN_GROWTH_INTERVAL", "14400"))  # 4 hours
# Client site monitoring cadence. 30 min between ticks; each tick checks at most
# 3 clients whose own 6-hour window has elapsed, so no site is hit often.
WATCH_INTERVAL = float(os.getenv("TITAN_WATCH_INTERVAL", "1800"))
# Six hours: a rebuild loses at most one window of work, and snapshotting never
# takes a noticeable share of the container's time.
BACKUP_INTERVAL = float(os.getenv("TITAN_BACKUP_INTERVAL", str(6 * 3600)))
# Re-measure every active self-improvement and roll back any that got worse.
# Six hours, so a regression doesn't sit in production for a day; the check
# re-measures each active parameter, so it isn't free.
IMPROVE_INTERVAL = float(os.getenv("TITAN_IMPROVE_INTERVAL", str(6 * 3600)))

# Seeded to now, not 0.0. `time.monotonic()` counts from system boot, so with
# 0.0 every scheduled cycle would fire on the first tick - a backup, an
# embedding-model download and every background cycle at once, before the app
# has served a request. Seeding to now makes the first run happen one real
# interval after boot.
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
        # The durable queue. Bounded per tick so a deep backlog can't monopolise
        # the heartbeat. It keeps crawls off the request path, and a container
        # recycled mid-audit retries instead of losing the work.
        with contextlib.suppress(Exception):
            from .core import queue
            await asyncio.to_thread(queue.drain, 3)
        # Answer any waiting Telegram commands (no-op with no token).
        with contextlib.suppress(Exception):
            from .engines import telegram_bot
            await asyncio.to_thread(telegram_bot.poll_once, STORE)
        # Client monitoring. Runs with nobody logged in, which is what makes the
        # service continuous rather than on-demand.
        if time.monotonic() - _last_watch >= WATCH_INTERVAL:
            _last_watch = time.monotonic()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(client_watch.cycle)
            # Titan audits its own site with the engine it sells. Rides the
            # client-watch tick instead of adding a timer; self_seo keeps its own
            # 6-hour interval, so calling it more often is a cheap no-op.
            with contextlib.suppress(Exception):
                from .engines import self_seo
                await asyncio.to_thread(self_seo.cycle)

            # Gives the audit, knowledge and watch engines real sites to work on.
            # Keeps its own 6-hour interval, so this is a no-op most of the time.
            with contextlib.suppress(Exception):
                from .engines import demo_workspace
                await asyncio.to_thread(demo_workspace.cycle)

            # Per-client news watch. Keeps its own 3-hour interval and round-robins a
            # few clients per tick, so a large portfolio never stalls the heartbeat.
            with contextlib.suppress(Exception):
                from .engines import client_news
                await asyncio.to_thread(client_news.cycle)

            # The scheduled half of the fix loop: enqueues re-audits for every
            # connected site and never applies anything. Keeps its own 6-hour
            # interval, so this is a cheap no-op most of the time.
            with contextlib.suppress(Exception):
                from .engines import fix_cycle
                await asyncio.to_thread(fix_cycle.cycle)

            # Embed anything indexed while the model was still downloading. Pages
            # ingested in the first minutes after a rebuild have no vectors; without
            # this they'd stay keyword-only until the next audit.
            #
            # On the heartbeat rather than the queue: it's idempotent, bounded by
            # MAX_PASSAGES, and a no-op when nothing is pending, so a job row per tick
            # would just be noise.
            with contextlib.suppress(Exception):
                from .core import knowledge
                await asyncio.to_thread(knowledge.backfill)

            with contextlib.suppress(Exception):
                from .core import queue
                await asyncio.to_thread(queue.trim)

            # A scheduled, self-verifying backup with its own interval. Titan holds
            # the only copy of the previous content of pages it has changed on
            # customers' sites; losing that store loses the ability to undo them.
            if time.monotonic() - _last_backup >= BACKUP_INTERVAL:
                globals()["_last_backup"] = time.monotonic()
                with contextlib.suppress(Exception):
                    from .core import backup
                    made = await asyncio.to_thread(backup.create, "scheduled")
                    # Only upload a backup that verified (backup restores it into a scratch
                    # database and counts rows); uploading a failed one would replace a good
                    # snapshot with a broken one.
                    #
                    # The path is at manifest["file"]; there's no top-level "path" key.
                    manifest = (made or {}).get("manifest") or {}
                    if (made or {}).get("ok") and manifest.get("verified") \
                            and manifest.get("file"):
                        from .core import remote_state as _remote
                        if _remote.configured():
                            await asyncio.to_thread(
                                _remote.push, manifest["file"],
                                note="scheduled")

            # The automatic half of the self-improvement loop: improve.check_active()
            # re-measures every active change and rolls back any that got worse.
            #
            # Safe to run automatically because it only goes one way: it never
            # proposes, approves or activates, it only moves a value back to one a
            # person already approved.
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
    # First, before anything is loaded or served. A deployment that enforces
    # authentication with no usable TITAN_SECRET must not answer a single
    # request, or it would sign founder sessions and encrypt the WordPress
    # credential vault with a published key. Deliberately not wrapped in
    # contextlib.suppress - this is meant to stop the boot. See
    # core/appsecret.py.
    from .core import appsecret as _appsecret
    _appsecret.verify_at_startup()

    # Before anything reads the database. A free Space wipes /tmp on every
    # rebuild, so on a fresh container the state file is absent and the latest
    # verified snapshot is pulled from a free private Dataset repo.
    # `remote_state.pull` refuses if a state file already exists, so this only
    # ever restores into an empty database. The outcome is always recorded, so a
    # failed restore (expired token, renamed repo, Hub outage) doesn't look like
    # a healthy first boot.
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
    # Seed the founder account from the environment, which retires the
    # environment-password gate in core/auth.py. Idempotent and never raises: a
    # deployment without TITAN_FOUNDER_EMAIL keeps the old gate and says so on
    # /api/auth. Unlike the secret check above, being unconfigured here is a
    # downgrade, not a danger.
    with contextlib.suppress(Exception):
        from .core import identity as _identity
        _identity.ensure_founder()
    opportunity.discover(STORE)
    ensure_weights(STORE)
    # Register the external-capability adapters. Idempotent, no network, no
    # optional-package imports - an unconfigured tool just reports what it needs.
    from .engines import adapters
    adapters.register_all()
    # Re-apply approved parameter overrides to the live modules; otherwise an
    # approved improvement would silently revert on the next rebuild.
    with contextlib.suppress(Exception):
        from .core import params as _params
        _params.apply_stored()
    # Bind job kinds to their handlers before the heartbeat drains anything, so
    # work left in the queue by a previous container is picked up on this boot.
    with contextlib.suppress(Exception):
        from .engines import fix_cycle
        fix_cycle.register_handlers()

    async def _initial_sync() -> None:
        # Same gate as the heartbeat: these are network round trips (GitHub,
        # CareerMind, a live web-research cycle) on every app start, which in the test
        # suite means every TestClient.
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
        # A free Space often rebuilds sooner than six hours, so waiting a full
        # interval could mean no backup ever gets taken. A backup takes ~20ms, so
        # taking one here is cheap.
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

# Paths that never need a login token: the login screen, health checks, public
# product pages, and the automation endpoints Make.com calls (it has no login
# token). The automation ones are low-risk: content generation and append-only
# logging.
_OPEN_PATHS = {
    # Paddle cannot hold a Titan token; the HMAC signature authenticates it
    # (api/router.py billing_webhook), and no secret means nothing is accepted.
    "/api/webhooks/billing",
    "/api/login",
    "/api/auth",
    "/api/demo/enter",
    # Opens the customer product for a stranger, with no token. Public on purpose:
    # it's the demo. It can only reach a business Titan owns - see
    # demo_workspace.showcase(), which returns None rather than falling back to a
    # real client.
    "/api/demo/portal",
    # The subscriber cockpit on the read-only demo account (router.py
    # enter_cockpit_demo). Public for the same reason: it is the demo.
    "/api/demo/cockpit",
    "/api/session",
    "/health",
    # /api/voice-report and /api/assistant aren't open: the founder's screens send
    # the founder token, and subscribers ask through /api/me.
    "/api/intelligence",
    "/api/llm/health",
    "/api/tts/health",
    "/api/doctor",
    "/api/content/daily",
    "/api/intel/news",
    "/api/inbox/auto-reply",
    # Public product surface: pricing has to be readable and signup reachable
    # without a founder token, or nobody can become a customer.
    "/api/plans",
    "/api/signup",
    "/api/account/login",
    # Titan's own audit score and product schema are marketing assets, meant to be
    # read by strangers and crawlers.
    "/api/self-seo",
    "/api/structured-data",
    # The client portal is handled by _OPEN_PREFIXES below, not here.
    # /api/revenue/log is deliberately not open: it writes to the real money
    # ledger, so it needs the founder token or the X-Webhook-Secret header.
    # Make.com must send:  X-Webhook-Secret: <TITAN_WEBHOOK_SECRET>
}


# Every /api/client/* route has its own credential (X-Client-Token), is scoped
# to one business, and fails closed on an unknown token, so the whole prefix
# can skip the founder token guard without weakening it. Admin client
# management stays behind the founder token. A prefix rather than a list, so a
# new client endpoint doesn't 401 until someone remembers to register it.
#
# /api/account and /api/checkout/* carry their own credential (X-Account-Token)
# scoped to one subscriber, and /api/org uses an identity session scoped to one
# organisation by membership. All fail closed on an unknown token, so they skip
# the founder guard the same way.
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

    Cloudflare can serve a managed AI-content-signals robots.txt at the zone
    level, which takes precedence at the edge and doesn't declare a sitemap.
    If titanomega-ai.com isn't returning this file, disable the managed
    robots.txt in the Cloudflare dashboard.
    """
    from .engines import self_seo
    return Response(content=self_seo.robots_txt(), media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Titan's audit flags a missing sitemap on client sites, so its own site
    serves one.
    """
    from .engines import self_seo
    return Response(content=self_seo.sitemap_xml(),
                    media_type="application/xml")


@app.get("/privacy", include_in_schema=False)
def privacy_page():
    """Privacy policy. Signup collects email addresses and the target market is
    the EU, and Titan's own audit flags a missing policy as legal-critical.
    """
    return _static_page("privacy.html")


@app.get("/terms", include_in_schema=False)
def terms_page():
    """Terms of service and refund policy, which Paddle's seller review checks
    for before approving a merchant.
    """
    return _static_page("terms.html")


@app.get("/refunds", include_in_schema=False)
def refunds_page():
    return _static_page("refunds.html")


@app.get("/pricing", include_in_schema=False)
def pricing_page_with_schema():
    """Pricing, with the product JSON-LD injected server-side.

    Google runs JavaScript, but most AI answer-engine crawlers don't, so schema
    added after hydration would never be seen by them. Injected per request
    rather than baked into the file, so the marked-up prices come from the live
    plan table and can't drift from what's charged.
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
    # Escaping "</" stops a stray closing tag inside the JSON from ending the
    # script element early.
    ld = ld.replace("</", "<\\/")
    tag = f'<script type="application/ld+json">{ld}</script>\n</head>'
    return Response(content=html.replace("</head>", tag, 1),
                    media_type="text/html")


@app.get("/compliance/{code}", include_in_schema=False)
def compliance_landing(code: str):
    """Per-jurisdiction legal requirements, server-rendered.

    The dashboard is a client-rendered SPA; a page meant to be found by search
    has to be readable with JavaScript off.
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
    """Signup -> pick a plan -> add a business -> first audit -> PDF, on one screen.

    Static like /pricing: this is where a stranger decides whether Titan is
    worth trying, so it has to render before the dashboard bundle would have
    downloaded. It holds no logic - every number and limit comes from the API
    that enforces them.
    """
    return _static_page("join.html")


@app.get("/portal", include_in_schema=False)
def client_portal():
    """The screen a client logs into. Static, no build step."""
    return _static_page("client.html")


@app.get("/clients", include_in_schema=False)
def admin_console():
    """The founder's console: every managed business on one screen.

    The page itself is public HTML with no data. Everything it shows comes
    from /api/admin/*, which stays behind the founder token.
    """
    return _static_page("admin.html")


@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """Never let browsers cache the HTML shell. Next.js chunks are content-hashed
    (safe to cache forever), but a cached index.html keeps pointing at old
    chunks, which shows a stale dashboard.

    The service worker script is the same kind of file: a fix to it only
    reaches browsers if nothing between them and the app holds an old copy.
    """
    resp = await call_next(request)
    if ("text/html" in resp.headers.get("content-type", "")
            or request.url.path == "/sw.js"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


_ASSET_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico",
                   ".webp", ".woff", ".woff2", ".map", ".json", ".txt", ".xml",
                   ".webmanifest")


@app.middleware("http")
async def count_visitors(request: Request, call_next):
    """Count HTML page loads so the founder can see who opened the site.

    Only page loads: counting assets and API calls would turn one visit into
    thirty. See core/traffic.py for why no IP is stored.
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
                # Behind the Cloudflare Worker the socket peer is Cloudflare, not the
                # visitor; the real address is in CF-Connecting-IP.
                ip=(request.headers.get("cf-connecting-ip")
                    or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                    or client_host),
                user_agent=request.headers.get("user-agent", ""),
                referrer=request.headers.get("referer", ""),
                # Cloudflare adds this on every proxied request, free and without an IP
                # database. Country only, deliberately.
                country=request.headers.get("cf-ipcountry", ""),
            )
    except Exception:
        pass
    return resp


@app.middleware("http")
async def bill_to(request: Request, call_next):
    """Say which subscriber this request is billed to, once.

    Read by core/quota.py, which core/llm.py checks before spending a model
    call. Bound here rather than in each route that resolves an account token,
    so no route can forget it.

    An absent or unknown token binds nothing, and unbound work is neither
    charged nor refused: founder work, the heartbeat engines and the public
    demo aren't a subscriber's usage.
    """
    from .core import quota
    quota.bind("")
    # A customer cockpit call was already authenticated by auth_guard, which runs
    # first and has rewritten /api/me/<x> to /api/<x>. Bill that customer.
    from .core import cockpit_scope
    if cockpit_scope.is_customer():
        quota.bind(cockpit_scope.customer_email())
        return await call_next(request)
    token = request.headers.get("x-account-token", "").strip()
    if token:
        with contextlib.suppress(Exception):
            from .core import billing as _billing
            quota.bind(_billing.resolve(token) or "")
    return await call_next(request)


async def _serve_customer_cockpit(request: Request, call_next, path: str):
    """A subscriber's cockpit call: /api/me/<x> is served by /api/<x>, from
    their own workspace, and only for routes on cockpit_scope.ALLOWED.

    Always requires the account token, whether or not founder auth is on:
    this door exists only for signed-in subscribers.
    """
    from .core import billing as _billing, cockpit_scope, workspaces
    from . import store as _store

    tok = (request.headers.get("x-account-token", "")
           or request.headers.get("authorization", "").removeprefix("Bearer ")).strip()
    email = _billing.resolve(tok) if tok else None
    if not email:
        return JSONResponse({"detail": "Sign in first"}, status_code=401)
    inner = "/api" + path[len("/api/me"):]
    if not cockpit_scope.allowed(request.method, inner):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    request.scope["path"] = inner
    request.scope["raw_path"] = inner.encode()
    store_token = _store.bind(workspaces.for_account(email))
    who_token = cockpit_scope.bind_customer(email)
    try:
        workspaces.touch(email)
        return await call_next(request)
    finally:
        cockpit_scope.unbind_customer(who_token)
        _store.unbind(store_token)


def _is_demo_request(request: Request) -> bool:
    from .core import billing as _billing
    tok = (request.headers.get("x-account-token", "")
           or request.headers.get("authorization", "").removeprefix("Bearer ")).strip()
    return bool(tok) and _billing.is_demo(_billing.resolve(tok) or "")


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    # The public demo account can read everything and change nothing, on /api/me
    # and the older /api/account door alike, since its token is an ordinary
    # account token and would otherwise open both.
    if request.method not in ("GET", "HEAD", "OPTIONS") and _is_demo_request(request):
        return JSONResponse({"detail": ("This is the demo. Sign up free to do "
                                        "this in your own workspace."),
                             "demo": True}, status_code=403)
    if path == "/api/me" or path.startswith("/api/me/"):
        return await _serve_customer_cockpit(request, call_next, path)
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
                    # Any private path without a sample is refused outright - fail closed.
                    return JSONResponse({"detail": "Hidden in demo", "guest": True}, status_code=403)
                return await call_next(request)

            # Automation (Make.com) can authenticate with the webhook secret instead.
            secret = request.headers.get("x-webhook-secret", "")
            expected = os.getenv("TITAN_WEBHOOK_SECRET")
            if not (expected and secret == expected):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


# Registered last on purpose. Starlette's `add_middleware` inserts at the front
# of the list, so the last one registered is outermost and runs first. Declared
# any earlier, this would sit inside `auth_guard`, and 401/403 responses (the
# ones you most want logged) would never be logged.
@app.middleware("http")
async def request_log(request: Request, call_next):
    """One structured line per request, with an id that follows the work.

    The id is returned in `X-Request-Id`, so a customer reporting a problem can
    quote it. An inbound `X-Request-Id` is kept (truncated) so a trace survives
    a proxy hop.
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
    # Assets are most of the traffic and none of the signal; logging every chunk
    # would bury the API calls that matter.
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
app.include_router(mine_router)


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
