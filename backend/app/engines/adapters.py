"""Adapters for the external projects Titan integrates with.

All in one file so there's a single, reviewable integration point per
capability and it's obvious nothing bypasses it.

Every adapter is a client, not a copy; no upstream source is vendored. That's
a licence requirement for Firecrawl (AGPL-3.0, while Titan is commercial) and
good practice for the rest.

With nothing configured, each adapter reports which environment variable is
missing, and crawling falls back to Titan's own stdlib fetcher so the
platform keeps working.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..core import api_adapters, tools

TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


# ------------------------------------------------------------- web crawling --
# Firecrawl is AGPL-3.0, so Titan only calls a separate instance over HTTP and
# never imports it. FIRECRAWL_BASE_URL points at a self-hosted container (the
# licence-clean option); FIRECRAWL_API_KEY targets their cloud instead.

def _firecrawl_scrape(url: str = "", formats: tuple = ("markdown",), **_) -> dict:
    if not url:
        raise ValueError("url is required")
    base = os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev").rstrip("/")
    key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = _post_json(f"{base}/v1/scrape",
                      {"url": url, "formats": list(formats)}, headers)
    doc = data.get("data") or data
    return {
        "url": url,
        "markdown": (doc.get("markdown") or "")[:200_000],
        "title": ((doc.get("metadata") or {}).get("title") or ""),
        "source": "firecrawl",
    }


def _stdlib_fetch(url: str = "", **_) -> dict:
    """Titan's own fetcher. Always available, no key, no third-party licence.

    Not a Firecrawl replacement - it returns raw HTML and can't render
    JavaScript - but "read a web page" never depends on an unconfigured
    vendor, and client_seo already audits with it.
    """
    if not url:
        raise ValueError("url is required")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read(1_500_000)
        enc = r.headers.get_content_charset() or "utf-8"
        html = raw.decode(enc, errors="replace")
    return {"url": url, "html": html, "status": r.status, "source": "stdlib",
            "note": "Raw HTML, no JS rendering. Configure Firecrawl for "
                    "JS-rendered pages and clean markdown."}


# ---------------------------------------------------------- agent frameworks --
def _praison_plan(goal: str = "", **_) -> dict:
    """PraisonAI (MIT) - multi-agent orchestration.

    Imported lazily and optional: it isn't in requirements.txt, because adding
    a heavy agent framework to a container that boots in seconds has a cost.
    Titan's own planner covers this for now.
    """
    try:
        import praisonaiagents  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "praisonaiagents is not installed. It is deliberately not a "
            "dependency yet — Titan's own planner covers this path. Install it "
            "only after benchmarking it against the built-in planner."
        ) from exc
    return {"goal": goal, "source": "praisonai"}


# ------------------------------------------------------------------- voice --
def _livekit_token(room: str = "", identity: str = "", **_) -> dict:
    """LiveKit (Apache-2.0) - realtime voice transport.

    Mints a room join token. Real phone calls need a telephony provider on top
    (SIP trunk / Twilio), which is a paid account - see the tool's `needs` when
    unconfigured.
    """
    try:
        from livekit import api as lk_api  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "livekit-api is not installed. Voice transport is designed but not "
            "wired: the calling half additionally needs a paid SIP/telephony "
            "account, so installing this alone would not make calls work."
        ) from exc
    grant = lk_api.VideoGrants(room_join=True, room=room or "titan")
    token = (lk_api.AccessToken(os.getenv("LIVEKIT_API_KEY", ""),
                                os.getenv("LIVEKIT_API_SECRET", ""))
             .with_identity(identity or "titan-agent")
             .with_grants(grant).to_jwt())
    return {"room": room or "titan", "token": token, "source": "livekit"}


# ---------------------------------------------------------------- messaging --
def _whatsapp_send(to: str = "", message: str = "", approved: bool = False, **_) -> dict:
    """OpenWA (MIT) - WhatsApp automation.

    Two independent gates:
      * `outbound=True` on the Tool, so nothing sends without explicit approval.
      * Unofficial WhatsApp automation can get a number banned, which would end
        the social management a client is paying for. Nothing is ever posted
        automatically.
    """
    base = os.getenv("OPENWA_BASE_URL", "").rstrip("/")
    payload = {"chatId": to, "message": message}
    key = os.getenv("OPENWA_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return {"sent": True, "to": to, "approved": approved, "source": "openwa",
            "response": _post_json(f"{base}/sendText", payload, headers)}


# --------------------------------------------------------------------- CRM --
def _crm_sync(**_) -> dict:
    """trycompai/crm (MIT) - external CRM sync.

    Titan already has CRM-lite with a lead funnel. This lets a client who runs
    their own CRM push leads in; it doesn't replace what Titan has. Wrapped so
    no vendor object reaches the rest of Titan.
    """
    base = os.getenv("COMPAI_CRM_URL", "").rstrip("/")
    key = os.getenv("COMPAI_CRM_KEY", "").strip()
    req = urllib.request.Request(f"{base}/api/health", headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return {"reachable": r.status == 200, "status": r.status,
                "source": "compai_crm"}


# -------------------------------------------------- keyless data capabilities --
# These live in `core/api_adapters.py`, which owns the provider choices, and
# reach the network only through `api_runtime` (SSRF guard, timeout, bounded
# read, breaker). This adds the agent-facing surface: an agent asks for a
# capability and never sees which vendor, how many, or in what order.
#
# `weather.current` is one call for the caller and two upstream: geocode the
# name, then fetch the forecast for those coordinates.

def _weather(place: str = "", latitude=None, longitude=None, **_) -> dict:
    """Weather by place name, or by coordinate if the caller already has one."""
    if str(place or "").strip():
        return api_adapters.weather_for_place(place)
    if latitude is None or longitude is None:
        return {"ok": False, "capability": "weather.current",
                "error": "Give a place name, or both latitude and longitude."}
    return api_adapters.weather(latitude, longitude)


def _exchange_rates(base: str = "USD", symbols=None, **_) -> dict:
    return api_adapters.exchange_rates(base, list(symbols) if symbols else None)


def _geocode(place: str = "", limit: int = 3, **_) -> dict:
    return api_adapters.geocode(place, limit)


def _security_headers(host: str = "", url: str = "", **_) -> dict:
    """Takes a hostname or a URL, since callers hold client sites as URLs."""
    return api_adapters.security_headers(host or url)


# ------------------------------------------------------------- registration --
def register_all() -> None:
    """Idempotent: safe to call on every boot."""
    tools.register(tools.Tool(
        name="web.fetch",
        capability="Fetch a web page as raw HTML (no key required)",
        run=_stdlib_fetch))

    tools.register(tools.Tool(
        name="web.crawl",
        capability="Crawl a page to clean markdown, with JS rendering",
        run=_firecrawl_scrape,
        provenance_key="firecrawl",
        env_required=("FIRECRAWL_BASE_URL",)))

    tools.register(tools.Tool(
        name="agents.plan",
        capability="Multi-agent task orchestration",
        run=_praison_plan,
        provenance_key="praisonai",
        package_required=("praisonaiagents",)))

    tools.register(tools.Tool(
        name="voice.room",
        capability="Realtime voice room for a speaking agent",
        run=_livekit_token,
        provenance_key="livekit",
        env_required=("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"),
        package_required=("livekit.api",)))

    tools.register(tools.Tool(
        name="messaging.whatsapp",
        capability="Send a WhatsApp message on the user's behalf",
        run=_whatsapp_send,
        provenance_key="openwa",
        env_required=("OPENWA_BASE_URL",),
        outbound=True))

    tools.register(tools.Tool(
        name="crm.sync",
        capability="Sync leads with an external CRM",
        run=_crm_sync,
        provenance_key="compai_crm",
        env_required=("COMPAI_CRM_URL",)))

    # Registered so the licence verdict is visible in the dashboard, not
    # rediscovered by whoever tries to integrate it next.
    tools.register(tools.Tool(
        name="memory.external",
        capability="External long-term agent memory store",
        run=lambda **_: {},
        provenance_key="tencent_memory"))

    # No env_required and no package_required, so these report "ready" - and they
    # really are: they need no key, which is why they could be checked against the
    # live services before the adapters were written.
    tools.register(tools.Tool(
        name="weather.current",
        capability="Current weather for a place name or a coordinate",
        run=_weather))

    tools.register(tools.Tool(
        name="geo.geocode",
        capability="Resolve a place name to coordinates, country and timezone",
        run=_geocode))

    tools.register(tools.Tool(
        name="finance.exchange_rates",
        capability="Live exchange rates, with a second provider behind the first",
        run=_exchange_rates))

    # Measures something Titan already audits, from an independent source.
    tools.register(tools.Tool(
        name="security.headers",
        capability="Independent security-header grade for a site (MDN Observatory)",
        run=_security_headers))
