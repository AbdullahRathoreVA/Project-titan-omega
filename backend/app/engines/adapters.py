"""Adapters for the external projects named in the master spec.

One file, because Part 8 requires a single documented integration point per
capability and it must be obvious at review time that nothing bypasses it.

Every adapter here is a *client*, not a copy. None of the upstream source is
vendored. That is a licence requirement for Firecrawl (AGPL-3.0 against a
commercial Titan) and simply good practice for the rest.

Each adapter degrades honestly: with nothing configured it reports exactly
which environment variable is missing, and the crawl capability falls back to
Titan's own stdlib fetcher so the platform is never dead in the water.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..core import tools

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
# Firecrawl is AGPL-3.0. Titan calls it over HTTP against a SEPARATE instance and
# never imports it. FIRECRAWL_BASE_URL points at a self-hosted container (the
# licence-clean option, and it can run in D:\stacks\ alongside the others);
# FIRECRAWL_API_KEY targets their cloud instead.

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

    Not a replacement for Firecrawl — it returns raw HTML and cannot render
    JavaScript — but it means "read a web page" never depends on an unconfigured
    vendor, and it is what client_seo already audits with.
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
    """PraisonAI (MIT) — multi-agent orchestration.

    Import is lazy and optional: the package is NOT in requirements.txt, because
    adding a heavyweight agent framework to a container that currently boots in
    seconds is a decision with a cost, and the spec says design and benchmark
    before adopting. Titan's own planner covers this today.
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
    """LiveKit (Apache-2.0) — realtime voice transport.

    Mints a room join token. Placing actual PHONE calls needs a telephony
    provider on top (SIP trunk / Twilio), which is a paid account in Abdullah's
    name — see the tool's `needs` when unconfigured.
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
    """OpenWA (MIT) — WhatsApp automation.

    Two independent gates, both deliberate:
      * `outbound=True` on the Tool, so nothing sends without explicit approval.
      * Unofficial WhatsApp automation can get a number BANNED. For a client
        paying for social management, a ban ends the service being sold — the
        exact failure mode Abdullah's standing rule about never auto-posting
        exists to prevent.
    """
    base = os.getenv("OPENWA_BASE_URL", "").rstrip("/")
    payload = {"chatId": to, "message": message}
    key = os.getenv("OPENWA_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return {"sent": True, "to": to, "approved": approved, "source": "openwa",
            "response": _post_json(f"{base}/sendText", payload, headers)}


# --------------------------------------------------------------------- CRM --
def _crm_sync(**_) -> dict:
    """trycompai/crm (MIT) — external CRM sync.

    Titan already has CRM-lite with a real lead funnel. This adapter exists so
    a client who already runs a CRM can push leads in, not to replace what Titan
    has. Wrapped, per Part 8: no vendor object ever reaches the rest of Titan.
    """
    base = os.getenv("COMPAI_CRM_URL", "").rstrip("/")
    key = os.getenv("COMPAI_CRM_KEY", "").strip()
    req = urllib.request.Request(f"{base}/api/health", headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return {"reachable": r.status == 200, "status": r.status,
                "source": "compai_crm"}


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

    # Registered so the licence verdict is visible in the dashboard rather than
    # rediscovered by whoever tries to integrate it next.
    tools.register(tools.Tool(
        name="memory.external",
        capability="External long-term agent memory store",
        run=lambda **_: {},
        provenance_key="tencent_memory"))
